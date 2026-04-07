"""Exception hierarchy for the Docker benchmark runner."""


class DockerRunnerError(Exception):
    """Base exception for all Docker runner errors."""


class ImplBuildError(DockerRunnerError):
    """Failed to build the implementation Docker image."""


class TestBuildError(DockerRunnerError):
    """Failed to build the test Docker image."""


class ImplStartupError(DockerRunnerError):
    """Implementation container exited prematurely during startup."""


class ImplStartupTimeout(DockerRunnerError):
    """Implementation container did not become ready within the timeout."""


class TestExecutionError(DockerRunnerError):
    """Test container failed to execute."""


class TestExecutionTimeout(DockerRunnerError):
    """Test container did not finish within the timeout."""


class ResultCollectionError(DockerRunnerError):
    """Failed to collect or parse test results."""
