"""Identity headers for the five roles of PRD §2.1.

`RatingProviderAdmin` carries an opaque operator identifier that is never
compared with any row's `id`, so a single shared header dict is enough — and
`X-User-ID` may legally be omitted for it.

The other four roles are entity-backed: `CertifiedRater`, `FieldInspector` and
`QADesignee` carry the `id` of the acting `Rater` row and `BuilderRep` carries
the `id` of the acting `Builder` row.  Those must therefore be built per
instance, from an id created earlier in the same test, which is what the
`make_*_headers` builders below are for.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ADMIN,
    ROLE_BUILDER_REP,
    ROLE_INSPECTOR,
    ROLE_QA,
    ROLE_RATER,
)

#: Opaque operator identifier for provider back-office staff (§2.1).
ADMIN_USER_ID = "provider-operator-1"

#: Provider staff headers.  Used for every RatingProviderAdmin call.
ADMIN_HEADERS: Dict[str, str] = build_user_headers(ADMIN_USER_ID, ROLE_ADMIN)

#: §2.1: `X-User-ID` "may be omitted only when `X-User-Role` is
#: `RatingProviderAdmin`".
ADMIN_HEADERS_WITHOUT_USER_ID: Dict[str, str] = {
    "X-User-Role": ROLE_ADMIN,
    "Content-Type": "application/json",
}


def make_certified_rater_headers(rater_id: str) -> Dict[str, str]:
    """`CertifiedRater` acting as the `Rater` row whose id is `rater_id`."""
    return build_user_headers(rater_id, ROLE_RATER)


def make_field_inspector_headers(rater_id: str) -> Dict[str, str]:
    """`FieldInspector` acting as the `Rater` row whose id is `rater_id`."""
    return build_user_headers(rater_id, ROLE_INSPECTOR)


def make_qa_designee_headers(rater_id: str) -> Dict[str, str]:
    """`QADesignee` acting as the `Rater` row whose id is `rater_id`."""
    return build_user_headers(rater_id, ROLE_QA)


def make_builder_rep_headers(builder_id: str) -> Dict[str, str]:
    """`BuilderRep` acting as the `Builder` row whose id is `builder_id`."""
    return build_user_headers(builder_id, ROLE_BUILDER_REP)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary role/user pairing, for authorization-negative cases."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> Dict[str, str]:
    """A request that omits `X-User-Role` entirely (§2.1 -> ERR_UNAUTHENTICATED)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str, role: str = "SiteSuperintendent") -> Dict[str, str]:
    """A request whose `X-User-Role` is not one of the five declared strings."""
    return build_user_headers(user_id, role)
