"""Caller identities.

Every request carries ``X-User-ID`` (the acting principal) and ``X-User-Role``
(the capacity in which it acts). Two of the four roles thread a real resource
identifier through ``X-User-ID``:

* a ``BondedCarrier`` presents the ``id`` of its own ``BondedCarrier`` record;
* a ``SuretyAgent`` presents the ``id`` of the ``CustomsBond`` it underwrites.

``CBPOfficer`` and ``FPFOfficer`` identifiers are opaque strings, so they can be
fixed constants; two distinct officer identities are needed because an officer
may not release a hold they placed, and the officer who issued a claim may
neither decide a petition against it nor dispose of it.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BONDED_CARRIER,
    ROLE_CBP_OFFICER,
    ROLE_FPF_OFFICER,
    ROLE_SURETY_AGENT,
)

# --- Opaque officer identities ---------------------------------------------
CBP_OFFICER_1_ID = "OFF-1"
CBP_OFFICER_2_ID = "OFF-2"
FPF_OFFICER_ID = "FPF-9"

CBP_OFFICER_1 = build_user_headers(CBP_OFFICER_1_ID, ROLE_CBP_OFFICER)
CBP_OFFICER_2 = build_user_headers(CBP_OFFICER_2_ID, ROLE_CBP_OFFICER)
FPF_OFFICER = build_user_headers(FPF_OFFICER_ID, ROLE_FPF_OFFICER)

#: An FPF officer whose identifier collides with the CBP officer that issues
#: claims in the fixtures — used to exercise the issuer-cannot-decide bar.
FPF_OFFICER_AS_ISSUER = build_user_headers(CBP_OFFICER_1_ID, ROLE_FPF_OFFICER)


def make_bonded_carrier_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for a carrier acting on its own movements."""
    return build_user_headers(carrier_id, ROLE_BONDED_CARRIER)


def make_surety_agent_headers(bond_id: str) -> Dict[str, str]:
    """Headers for the surety agent of one specific bond."""
    return build_user_headers(bond_id, ROLE_SURETY_AGENT)


def make_cbp_officer_headers(officer_id: str) -> Dict[str, str]:
    return build_user_headers(officer_id, ROLE_CBP_OFFICER)


def make_fpf_officer_headers(officer_id: str) -> Dict[str, str]:
    return build_user_headers(officer_id, ROLE_FPF_OFFICER)


def headers_without_role(user_id: str) -> Dict[str, str]:
    """A request that omits ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """A request that omits ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_identity() -> Dict[str, str]:
    """A wholly anonymous request: neither identity header is present."""
    return {"Content-Type": "application/json"}
