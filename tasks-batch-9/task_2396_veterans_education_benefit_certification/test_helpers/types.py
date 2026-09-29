"""Lightweight type aliases shared by the helper modules and the test suite."""

from typing import Any, Dict, List

#: Auth headers as sent on every request: X-User-ID plus X-User-Role.
Headers = Dict[str, str]

#: A decoded JSON object, e.g. the ``data`` payload of a single-resource response.
JsonDict = Dict[str, Any]

#: A decoded JSON array, e.g. the ``data`` payload of a list response.
JsonList = List[JsonDict]
