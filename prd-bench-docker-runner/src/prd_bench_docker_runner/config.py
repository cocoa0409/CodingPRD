"""Run configuration for the Docker benchmark runner."""

from dataclasses import dataclass, field
from pathlib import Path
import uuid


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class RunConfig:
    task_dir: Path
    impl_dir: Path
    port: int = 10000
    build_timeout: int = 300
    startup_timeout: int = 60
    test_timeout: int = 600
    results_file: Path | None = None
    run_id: str = field(default_factory=_short_id)
    keep_containers: bool = False
    log_level: str = "INFO"
    runner_source_dir: Path | None = None  # path to prd-bench-local-runner/ source

    def __post_init__(self):
        self.task_dir = Path(self.task_dir).resolve()
        self.impl_dir = Path(self.impl_dir).resolve()
        if self.results_file:
            self.results_file = Path(self.results_file).resolve()
        if self.runner_source_dir:
            self.runner_source_dir = Path(self.runner_source_dir).resolve()

    @property
    def test_suite_dir(self) -> Path:
        return self.task_dir / "test_suite"

    @property
    def test_helpers_dir(self) -> Path:
        return self.task_dir / "test_helpers"

    @property
    def test_dockerfile(self) -> Path:
        return self.task_dir / "Dockerfile.test"

    @property
    def impl_dockerfile(self) -> Path:
        return self.impl_dir / "Dockerfile"

    @property
    def network_name(self) -> str:
        return f"prd-bench-{self.run_id}"

    @property
    def impl_container_name(self) -> str:
        return f"prd-impl-{self.run_id}"

    @property
    def test_container_name(self) -> str:
        return f"prd-test-{self.run_id}"

    @property
    def impl_image_tag(self) -> str:
        return f"prd-impl:{self.run_id}"

    @property
    def test_image_tag(self) -> str:
        return f"prd-test:{self.run_id}"

    @property
    def volume_name(self) -> str:
        return f"prd-results-{self.run_id}"
