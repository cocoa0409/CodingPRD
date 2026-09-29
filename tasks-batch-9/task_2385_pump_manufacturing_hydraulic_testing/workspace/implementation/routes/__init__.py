from . import (  # noqa: F401
    builds,
    casting,
    clock,
    duty,
    kits,
    master,
    packages,
    testing,
    warranty,
)

BLUEPRINTS = [
    clock.bp,
    master.bp,
    duty.bp,
    casting.bp,
    builds.bp,
    testing.bp,
    packages.bp,
    kits.bp,
    warranty.bp,
]
