"""Docker operations: build images, run containers, manage networks, cleanup."""

import io
import tarfile
from pathlib import Path

import docker
from docker.errors import BuildError, APIError, ImageNotFound
from loguru import logger

from .config import RunConfig
from .errors import ImplBuildError, TestBuildError


class DockerOperations:
    def __init__(self, config: RunConfig):
        self.config = config
        self.client = docker.from_env()
        self._created_resources: list[tuple[str, str]] = []  # (type, name)

    # ── Network ──────────────────────────────────────────────

    def create_network(self):
        name = self.config.network_name
        logger.info(f"Creating Docker network: {name}")
        network = self.client.networks.create(name, driver="bridge")
        self._created_resources.append(("network", name))
        return network

    # ── Build implementation image ───────────────────────────

    def build_impl_image(self) -> str:
        tag = self.config.impl_image_tag
        path = str(self.config.impl_dir)
        logger.info(f"Building implementation image: {tag} from {path}")
        try:
            _, logs = self.client.images.build(
                path=path,
                tag=tag,
                rm=True,
                timeout=self.config.build_timeout,
            )
            for chunk in logs:
                if "stream" in chunk:
                    line = chunk["stream"].rstrip()
                    if line:
                        logger.debug(f"[impl-build] {line}")
            self._created_resources.append(("image", tag))
            return tag
        except (BuildError, APIError) as exc:
            raise ImplBuildError(f"Failed to build implementation image: {exc}") from exc

    # ── Build test image ─────────────────────────────────────

    def build_test_image(self) -> str:
        tag = self.config.test_image_tag
        logger.info(f"Building test image: {tag}")
        context_tar = self._assemble_test_build_context()
        try:
            _, logs = self.client.images.build(
                fileobj=context_tar,
                custom_context=True,
                tag=tag,
                rm=True,
                timeout=self.config.build_timeout,
            )
            for chunk in logs:
                if "stream" in chunk:
                    line = chunk["stream"].rstrip()
                    if line:
                        logger.debug(f"[test-build] {line}")
            self._created_resources.append(("image", tag))
            return tag
        except (BuildError, APIError) as exc:
            raise TestBuildError(f"Failed to build test image: {exc}") from exc

    def _assemble_test_build_context(self) -> io.BytesIO:
        """Build a tar archive containing:
        - Dockerfile (from task_dir/Dockerfile.test)
        - test_suite/ (from task_dir)
        - test_helpers/ (from task_dir)
        - prd-bench-local-runner/ (source package for prd_bench_local_runner.testing)
        """
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            # Dockerfile
            tar.add(
                str(self.config.test_dockerfile),
                arcname="Dockerfile",
            )
            # test_suite/
            tar.add(
                str(self.config.test_suite_dir),
                arcname="test_suite",
            )
            # test_helpers/
            tar.add(
                str(self.config.test_helpers_dir),
                arcname="test_helpers",
            )
            # prd-bench-local-runner/ source
            runner_src = self._find_runner_source()
            tar.add(str(runner_src), arcname="prd-bench-local-runner")

        buf.seek(0)
        return buf

    def _find_runner_source(self) -> Path:
        """Locate the prd-bench-local-runner source directory."""
        if self.config.runner_source_dir:
            return self.config.runner_source_dir

        # Walk up from this file to find the project root
        # Expected layout: project_root/prd-bench-local-runner/
        candidate = Path(__file__).resolve()
        for _ in range(10):
            candidate = candidate.parent
            runner_dir = candidate / "prd-bench-local-runner"
            if (runner_dir / "pyproject.toml").exists():
                return runner_dir

        raise FileNotFoundError(
            "Cannot find prd-bench-local-runner/ source directory. "
            "Use --runner-source-dir to specify it explicitly."
        )

    # ── Run containers ───────────────────────────────────────

    def run_impl_container(self, network):
        name = self.config.impl_container_name
        tag = self.config.impl_image_tag
        port = self.config.port
        logger.info(f"Starting implementation container: {name} (port {port})")
        container = self.client.containers.run(
            tag,
            name=name,
            network=network.name,
            ports={f"{port}/tcp": None},  # map to random host port
            environment={"PORT": str(port)},
            detach=True,
        )
        self._created_resources.append(("container", name))
        return container

    def run_test_container(self, network):
        name = self.config.test_container_name
        tag = self.config.test_image_tag
        port = self.config.port
        impl_name = self.config.impl_container_name
        api_url = f"http://{impl_name}:{port}"
        logger.info(f"Starting test container: {name} (API_BASE_URL={api_url})")
        env = {
            "API_BASE_URL": api_url,
            # Ensure HTTP proxy does not intercept container-to-container traffic
            "no_proxy": f"{impl_name},localhost,127.0.0.1",
            "NO_PROXY": f"{impl_name},localhost,127.0.0.1",
            "http_proxy": "",
            "https_proxy": "",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
        }
        container = self.client.containers.run(
            tag,
            name=name,
            network=network.name,
            environment=env,
            detach=True,
        )
        self._created_resources.append(("container", name))
        return container

    def wait_for_container(self, container, timeout: int) -> dict:
        """Wait for a container to exit. Returns {"StatusCode": int}."""
        try:
            return container.wait(timeout=timeout)
        except Exception as exc:
            logger.warning(f"Timeout or error waiting for container: {exc}")
            container.stop(timeout=5)
            raise

    def get_container_logs(self, container) -> str:
        return container.logs().decode("utf-8", errors="replace")

    def get_mapped_port(self, container, container_port: int) -> int | None:
        """Get the host port mapped to a container port."""
        container.reload()
        ports = container.ports
        key = f"{container_port}/tcp"
        if key in ports and ports[key]:
            return int(ports[key][0]["HostPort"])
        return None

    # ── Copy files from container ────────────────────────────

    def copy_from_container(self, container, src_path: str, dst_path: Path) -> bool:
        """Copy a file from a container to the host. Returns True on success."""
        try:
            bits, _ = container.get_archive(src_path)
            # get_archive returns a tar stream
            raw = b"".join(bits)
            tar_buf = io.BytesIO(raw)
            with tarfile.open(fileobj=tar_buf, mode="r") as tar:
                # Extract the single file
                members = tar.getmembers()
                if not members:
                    return False
                f = tar.extractfile(members[0])
                if f is None:
                    return False
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                dst_path.write_bytes(f.read())
            return True
        except Exception as exc:
            logger.warning(f"Failed to copy {src_path} from container: {exc}")
            return False

    # ── Cleanup ──────────────────────────────────────────────

    def cleanup(self):
        if self.config.keep_containers:
            logger.info(f"Keeping containers (--keep-containers). Resources: {self._created_resources}")
            return

        logger.info("Cleaning up Docker resources...")
        for resource_type, name in reversed(self._created_resources):
            try:
                if resource_type == "container":
                    try:
                        c = self.client.containers.get(name)
                        c.stop(timeout=5)
                    except Exception:
                        pass
                    try:
                        c = self.client.containers.get(name)
                        c.remove(force=True)
                    except Exception:
                        pass
                elif resource_type == "network":
                    try:
                        n = self.client.networks.get(name)
                        n.remove()
                    except Exception:
                        pass
                elif resource_type == "image":
                    try:
                        self.client.images.remove(name, force=True)
                    except ImageNotFound:
                        pass
                    except Exception:
                        pass
                logger.debug(f"Removed {resource_type}: {name}")
            except Exception as exc:
                logger.debug(f"Cleanup failed for {resource_type} {name}: {exc}")

        self._created_resources.clear()
