"""Calculation: home_state_determination (PRD 3.3).

Runs exactly once, at placement creation, and is never recomputed.
"""

from errors import ApiError


def determine(ppb_state, state_exposures):
    """Returns (home_state, total_insured_value_cents).

    Step 1 - an empty exposure schedule is refused outright.
    Step 2 - the principal place of business wins if and only if it carries
             STRICTLY positive exposure.
    Step 3 - otherwise the greatest insured value wins among positive rows,
             ties broken by the alphabetically smallest state_code.
    """
    if not state_exposures:
        raise ApiError("ERR_HOME_STATE_INDETERMINATE",
                       "state_exposures is empty; no home state can be determined.")

    total = sum(int(r["insured_value_cents"]) for r in state_exposures)

    ppb_rows = [r for r in state_exposures
                if r["state_code"] == ppb_state
                and int(r["insured_value_cents"]) > 0]
    if ppb_rows:
        return ppb_state, total

    positive = [r for r in state_exposures if int(r["insured_value_cents"]) > 0]
    if not positive:
        raise ApiError("ERR_HOME_STATE_INDETERMINATE",
                       "No exposure row carries a positive insured value.")
    best = max(int(r["insured_value_cents"]) for r in positive)
    home = min(r["state_code"] for r in positive
               if int(r["insured_value_cents"]) == best)
    return home, total
