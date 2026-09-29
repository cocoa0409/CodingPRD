"""Lightweight structural aliases for the API's JSON shapes.

The API speaks plain JSON, so these are documentation-grade aliases rather
than runtime validators.  They exist so that helper signatures can say what
they mean without importing anything heavy.
"""

from typing import Any, Dict, List, Optional, Tuple

# A decoded ``data`` object from a success envelope.
Json = Dict[str, Any]

# A decoded list payload plus its pagination ``meta``.
Page = Tuple[List[Json], Json]

# Request headers as the framework builds them.
Headers = Dict[str, str]

# Any request body.
Payload = Dict[str, Any]

# Resource identifiers are UUID strings assigned by the server.
ResourceId = str

# Money is always integer cents; ratios are always integer basis points.
Cents = int
Bps = int

# Dates are ``YYYY-MM-DD``; instants are ISO-8601 with a trailing ``Z``.
IsoDate = str
IsoInstant = str

OptionalJson = Optional[Json]
