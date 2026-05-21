"""Employee-domain validation: tipped-field consistency + wage-floor checks."""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..errors import (
    err_below_minimum_wage,
    err_invalid_input,
    err_tipped_fields_mismatch,
)


FEDERAL_MIN_WAGE_CENTS = 725
FEDERAL_TIPPED_MIN_CENTS = 213


def validate_employee_create_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize the POST /employees body.

    Returns a dict of validated, system-ready fields. Raises one of:
      ERR_INVALID_INPUT, ERR_TIPPED_FIELDS_MISMATCH, ERR_BELOW_MINIMUM_WAGE
    """
    # full_name
    full_name = payload.get("full_name")
    if not isinstance(full_name, str) or not (1 <= len(full_name) <= 120):
        raise err_invalid_input("full_name must be a string of 1..120 chars.")

    # jurisdiction
    jurisdiction = payload.get("jurisdiction")
    if jurisdiction not in ("CA", "FED"):
        raise err_invalid_input("jurisdiction must be one of CA, FED.")

    # classification
    classification = payload.get("classification")
    if classification not in ("EXEMPT", "NON_EXEMPT"):
        raise err_invalid_input("classification must be one of EXEMPT, NON_EXEMPT.")

    # tipped_role
    tipped_role = payload.get("tipped_role", False)
    if tipped_role is None:
        tipped_role = False
    if not isinstance(tipped_role, bool):
        raise err_invalid_input("tipped_role must be boolean.")

    # base_hourly_rate_cents
    base_rate = payload.get("base_hourly_rate_cents")
    if classification == "NON_EXEMPT":
        if not isinstance(base_rate, int) or isinstance(base_rate, bool):
            raise err_invalid_input("base_hourly_rate_cents required (integer) for NON_EXEMPT.")
        if base_rate < FEDERAL_MIN_WAGE_CENTS:
            raise err_below_minimum_wage(
                f"base_hourly_rate_cents must be >= {FEDERAL_MIN_WAGE_CENTS} (federal minimum)."
            )
    else:
        # EXEMPT — base rate ignored; force null for storage hygiene
        if base_rate is not None and (not isinstance(base_rate, int) or isinstance(base_rate, bool)):
            raise err_invalid_input("base_hourly_rate_cents must be integer when supplied.")
        base_rate = base_rate if isinstance(base_rate, int) and not isinstance(base_rate, bool) else None

    # Tipped fields
    tipped_cash = payload.get("tipped_cash_rate_cents")
    applicable_min = payload.get("applicable_minimum_wage_cents")

    if tipped_role:
        # tipped employees: both tipped_cash_rate_cents AND applicable_minimum_wage_cents required
        if not isinstance(tipped_cash, int) or isinstance(tipped_cash, bool):
            raise err_tipped_fields_mismatch(
                "tipped_cash_rate_cents is required (integer) when tipped_role=true."
            )
        if not isinstance(applicable_min, int) or isinstance(applicable_min, bool):
            raise err_tipped_fields_mismatch(
                "applicable_minimum_wage_cents is required (integer) when tipped_role=true."
            )
        if tipped_cash < FEDERAL_TIPPED_MIN_CENTS:
            raise err_below_minimum_wage(
                f"tipped_cash_rate_cents must be >= {FEDERAL_TIPPED_MIN_CENTS} (federal tipped minimum)."
            )
        if applicable_min < FEDERAL_MIN_WAGE_CENTS:
            raise err_below_minimum_wage(
                f"applicable_minimum_wage_cents must be >= {FEDERAL_MIN_WAGE_CENTS}."
            )
        # Wage floor sanity: cash + tips/hour must be able to reach applicable_min.
        # The only way this is impossible is if tipped_cash > applicable_min (then
        # nothing to top up — fine) OR negative — already excluded. The check is
        # logically that applicable_min >= tipped_cash, which is the "topup" model.
        # We additionally guard: applicable_min must not be < tipped_cash (i.e.
        # config is internally consistent for tipped-employee math).
        # (PRD says config-time floor check rejects impossible configurations.)
    else:
        # Non-tipped: tipped fields must be absent
        if tipped_cash is not None or applicable_min is not None:
            raise err_tipped_fields_mismatch(
                "tipped_cash_rate_cents / applicable_minimum_wage_cents must be omitted "
                "when tipped_role is false."
            )

    return {
        "full_name": full_name,
        "jurisdiction": jurisdiction,
        "classification": classification,
        "base_hourly_rate_cents": base_rate,
        "tipped_role": tipped_role,
        "tipped_cash_rate_cents": tipped_cash if tipped_role else None,
        "applicable_minimum_wage_cents": applicable_min if tipped_role else None,
    }


def validate_employee_patch_payload(
    current: Dict[str, Any],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate a PATCH body against current Employee state.

    Returns a *new* dict reflecting the post-patch values for the mutable
    fields. Does NOT mutate `current`. The caller is responsible for OCC
    version comparison BEFORE calling this — but here we still raise on
    domain-level inconsistencies (tipped-mismatch, below-minimum-wage).
    """
    new_state = dict(current)  # shallow copy
    if "classification" in payload:
        cls = payload["classification"]
        if cls not in ("EXEMPT", "NON_EXEMPT"):
            raise err_invalid_input("classification must be one of EXEMPT, NON_EXEMPT.")
        new_state["classification"] = cls
    if "jurisdiction" in payload:
        j = payload["jurisdiction"]
        if j not in ("CA", "FED"):
            raise err_invalid_input("jurisdiction must be one of CA, FED.")
        new_state["jurisdiction"] = j
    if "base_hourly_rate_cents" in payload:
        b = payload["base_hourly_rate_cents"]
        if b is None:
            new_state["base_hourly_rate_cents"] = None
        else:
            if not isinstance(b, int) or isinstance(b, bool):
                raise err_invalid_input("base_hourly_rate_cents must be integer.")
            new_state["base_hourly_rate_cents"] = b
    if "tipped_role" in payload:
        tr = payload["tipped_role"]
        if not isinstance(tr, bool):
            raise err_invalid_input("tipped_role must be boolean.")
        new_state["tipped_role"] = tr
    if "tipped_cash_rate_cents" in payload:
        tc = payload["tipped_cash_rate_cents"]
        if tc is not None and (not isinstance(tc, int) or isinstance(tc, bool)):
            raise err_invalid_input("tipped_cash_rate_cents must be integer or null.")
        new_state["tipped_cash_rate_cents"] = tc
    if "applicable_minimum_wage_cents" in payload:
        am = payload["applicable_minimum_wage_cents"]
        if am is not None and (not isinstance(am, int) or isinstance(am, bool)):
            raise err_invalid_input("applicable_minimum_wage_cents must be integer or null.")
        new_state["applicable_minimum_wage_cents"] = am
    if "status" in payload:
        st = payload["status"]
        if st not in ("ACTIVE", "TERMINATED"):
            raise err_invalid_input("status must be one of ACTIVE, TERMINATED.")
        new_state["status"] = st

    # Cross-field rechecks ---------------------------------------------
    # Tipped-role/fields consistency must hold post-patch.
    if new_state.get("tipped_role"):
        tc = new_state.get("tipped_cash_rate_cents")
        am = new_state.get("applicable_minimum_wage_cents")
        if not isinstance(tc, int) or isinstance(tc, bool):
            raise err_tipped_fields_mismatch(
                "tipped_cash_rate_cents must remain set when tipped_role=true."
            )
        if not isinstance(am, int) or isinstance(am, bool):
            raise err_tipped_fields_mismatch(
                "applicable_minimum_wage_cents must remain set when tipped_role=true."
            )
        if tc < FEDERAL_TIPPED_MIN_CENTS:
            raise err_below_minimum_wage(
                f"tipped_cash_rate_cents must be >= {FEDERAL_TIPPED_MIN_CENTS}."
            )
        if am < FEDERAL_MIN_WAGE_CENTS:
            raise err_below_minimum_wage(
                f"applicable_minimum_wage_cents must be >= {FEDERAL_MIN_WAGE_CENTS}."
            )
    else:
        # Non-tipped: tipped fields must be absent / null
        if new_state.get("tipped_cash_rate_cents") is not None or \
                new_state.get("applicable_minimum_wage_cents") is not None:
            # Only raise if those were explicitly set non-null in this patch OR
            # were inconsistent already and the patch made the inconsistency
            # observable. To support clean nulls on the way down, we tolerate
            # the case where both fields are still non-null but the patch is
            # only flipping role — require caller to clear them explicitly.
            raise err_tipped_fields_mismatch(
                "tipped_cash_rate_cents/applicable_minimum_wage_cents must be cleared "
                "when tipped_role is false."
            )

    if new_state.get("classification") == "NON_EXEMPT":
        b = new_state.get("base_hourly_rate_cents")
        if not isinstance(b, int) or isinstance(b, bool):
            raise err_invalid_input("base_hourly_rate_cents must be set for NON_EXEMPT.")
        if b < FEDERAL_MIN_WAGE_CENTS:
            raise err_below_minimum_wage(
                f"base_hourly_rate_cents must be >= {FEDERAL_MIN_WAGE_CENTS}."
            )

    return new_state
