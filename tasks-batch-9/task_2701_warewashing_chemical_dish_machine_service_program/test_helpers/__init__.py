"""
Test infrastructure for the Warewashing Chemical & Dish Machine Service Program API.

Submodules:
- `api_client`   — one method per §4 endpoint
- `api_errors`   — the §5 error catalogue and the §2.8 rule ladder
- `assertions`   — domain assertions over the §2.5 / §2.6 / §2.10 contracts
- `constants`    — every threshold, rate and canonical fixture value
- `factories`    — request payload builders
- `fixtures`     — composite state builders driven through PRD endpoints only
- `test_users`   — role headers and entity-backed identity builders
- `types`        — enum members transcribed from the PRD
"""

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import WarewashingApiClient  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, RULE_LADDER, ladder_rung  # noqa: F401

__all__ = [
    "WarewashingApiClient",
    "HTTP_STATUS_CODES",
    "RULE_LADDER",
    "ladder_rung",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
]
