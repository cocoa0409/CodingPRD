"""Light structural aliases for the JSON documents this API returns.

The service answers with a uniform envelope, so every helper in this package
speaks in plain dictionaries. These aliases exist only to make the signatures of
the factories, fixtures and assertions readable; nothing here validates.
"""

from typing import Any, Dict, List, Tuple

# A decoded JSON object, e.g. the `data` member of a success envelope.
Json = Dict[str, Any]

# A decoded JSON array of objects, e.g. the `data` member of a list envelope.
JsonList = List[Json]

# The `meta` member of a list envelope: limit / offset / total_count / has_more.
PageMeta = Dict[str, Any]

# What `validate_paginated` hands back.
Page = Tuple[JsonList, PageMeta]

# Request headers: X-User-ID / X-User-Role / Content-Type.
Headers = Dict[str, str]

# A request body.
Payload = Dict[str, Any]

# One entry of a reconciliation report's `platform_lines` input array.
PlatformLine = Dict[str, Any]

# One entry of a reconciliation report's `variance_lines` output array.
VarianceLine = Dict[str, Any]
