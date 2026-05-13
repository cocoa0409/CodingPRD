"""Package resolution service."""
from clock import parse_iso, clock

from db import store
from errors import raise_error, ERR_PACKAGE_NOT_FOUND, ERR_PACKAGE_VERSION_DUPLICATE


def resolve_package_at(package_code: str, when_dt=None):
    """Return PackageVersion with greatest effective_from <= when_dt, or None.

    when_dt defaults to clock.now()."""
    if when_dt is None:
        when_dt = clock.now()
    candidates = []
    for pv in store.package_versions.values():
        if pv["package_code"] != package_code:
            continue
        eff = parse_iso(pv["effective_from"])
        if eff <= when_dt:
            candidates.append((eff, pv))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def resolve_package_or_404(package_code: str, when_dt=None):
    pv = resolve_package_at(package_code, when_dt)
    if pv is None:
        raise_error(ERR_PACKAGE_NOT_FOUND,
                    f"No PackageVersion exists for {package_code}")
    return pv


def get_package_by_id_or_none(package_version_id: str):
    return store.package_versions.get(package_version_id)


def check_package_version_unique(package_code: str, version_number: int):
    for pv in store.package_versions.values():
        if pv["package_code"] == package_code and int(pv["version_number"]) == int(version_number):
            raise_error(ERR_PACKAGE_VERSION_DUPLICATE,
                        f"Package {package_code} version {version_number} already exists")
