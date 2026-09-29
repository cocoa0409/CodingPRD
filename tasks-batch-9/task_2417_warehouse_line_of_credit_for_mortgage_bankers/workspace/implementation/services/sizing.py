"""The five-stage sizing waterfall and the concentration solve (PRD 3.4)."""

from db import db
from errors import ApiError
from money import floor_cents, frac
from services import computed
from services.constants import (
    CONCENTRATION_FLOOR_CENTS,
    MIN_ADVANCE_CENTS,
    ORPHAN_RATE,
    ORPHANING_COMMITMENT_STATUSES,
)


def stage_one_two_rate(advance, row, commitment):
    """Stage one selects the base rate; stage two applies the orphan cap."""
    rate = frac(row["advance_rate"])
    if advance["funding_type"] == "WET":
        rate = rate - frac(row["wet_haircut"])
    if commitment is None or commitment["status"] in ORPHANING_COMMITMENT_STATUSES:
        rate = min(rate, ORPHAN_RATE)
    return rate


def provisional_amount(advance, row=None, commitment=None):
    """Stage three: the stage-two rate multiplied by loan_amount_cents, floored."""
    row = row or computed.advance_rate_row(advance)
    if commitment is None:
        commitment = computed.advance_commitment(advance)
    rate = stage_one_two_rate(advance, row, commitment)
    if rate < 0:
        rate = frac(0)
    return floor_cents(frac(advance["loan_amount_cents"]) * rate)


def concentration_constrained_advance(proposed, facility, commitment,
                                      pre_outstanding):
    """Stage five.  The step order is pinned because the constraint is circular:
    the ratio is measured on the post-funding outstanding, which itself contains
    the amount being solved for."""
    # step one / two / three
    hypothetical = pre_outstanding + proposed
    # step four: two short circuits
    if commitment is None:
        return proposed
    if hypothetical <= CONCENTRATION_FLOOR_CENTS:
        return proposed
    # step five
    investor = db.investors.get(commitment["investor_id"])
    exposure = computed.investor_exposure(commitment["investor_id"])
    cap = min(frac(facility["max_investor_concentration_pct"]),
              frac(investor["concentration_limit_pct"]))
    # step six: exact decimal arithmetic, no intermediate rounding
    if frac(exposure + proposed) <= cap * frac(hypothetical):
        return proposed
    # step seven
    denominator = frac(1) - cap
    if denominator <= 0:
        solved = 0
    else:
        solved = floor_cents((cap * frac(pre_outstanding) - frac(exposure))
                             / denominator)
    if solved < 0:
        solved = 0
    # step eight
    return min(proposed, solved)


def size_advance(advance, facility):
    """Run stages three through five and enforce priorities 35, 36 and 38-43.

    Returns (provisional, final, concentration_capped).
    """
    row = computed.advance_rate_row(advance)
    commitment = computed.advance_commitment(advance)
    provisional = provisional_amount(advance, row, commitment)

    facility_id = facility["id"]
    pre_outstanding = computed.outstanding_principal(facility_id)
    available = max(0, facility["committed_amount_cents"] - pre_outstanding)
    wet_headroom = facility["wet_sublimit_cents"] - computed.wet_outstanding(facility_id)
    sd_headroom = (facility["scratch_and_dent_sublimit_cents"]
                   - computed.scratch_and_dent_outstanding(facility_id))
    product_headroom = None
    if row["product_sublimit_cents"] is not None:
        product_headroom = (row["product_sublimit_cents"]
                            - computed.product_outstanding(facility_id,
                                                           advance["product_code"]))
    commitment_headroom = None
    if commitment is not None:
        commitment_headroom = computed.commitment_remaining(commitment)

    # stage four: the candidate list, and the smallest number wins
    caps = [available]
    if product_headroom is not None:
        caps.append(product_headroom)
    if advance["funding_type"] == "WET":
        caps.append(wet_headroom)
    if advance["product_code"] == "SCRATCH_AND_DENT":
        caps.append(sd_headroom)
    if commitment_headroom is not None:
        caps.append(commitment_headroom)

    final = 0
    capped = False
    if all(cap > 0 for cap in caps):
        stage_four = min([provisional] + caps)
        # priority 35
        if stage_four < MIN_ADVANCE_CENTS:
            raise ApiError(
                "ERR_ADVANCE_BELOW_MINIMUM",
                "The stage-four amount %d is below the minimum advance size."
                % stage_four)
        final = concentration_constrained_advance(stage_four, facility, commitment,
                                                  pre_outstanding)
        capped = final < stage_four
        # priority 36
        if final < MIN_ADVANCE_CENTS:
            raise ApiError(
                "ERR_INVESTOR_CONCENTRATION_EXCEEDED",
                "The concentration solve returned %d, below the minimum advance "
                "size." % final)

    # the fiscal tier, in priority order 38 through 43
    if available <= 0:
        raise ApiError("ERR_FACILITY_AVAILABILITY_EXCEEDED",
                       "The facility has no availability.")
    if advance["funding_type"] == "WET" and wet_headroom <= 0:
        raise ApiError("ERR_WET_SUBLIMIT_EXCEEDED",
                       "The wet bucket has no headroom.")
    if computed.aged_outstanding(facility_id) > facility["aged_sublimit_cents"]:
        raise ApiError("ERR_AGED_SUBLIMIT_EXCEEDED",
                       "The aged bucket has passed its sublimit.")
    if advance["product_code"] == "SCRATCH_AND_DENT" and sd_headroom <= 0:
        raise ApiError("ERR_SCRATCH_AND_DENT_SUBLIMIT_EXCEEDED",
                       "The scratch-and-dent bucket has no headroom.")
    if product_headroom is not None and product_headroom <= 0:
        raise ApiError("ERR_PRODUCT_SUBLIMIT_EXCEEDED",
                       "The product sublimit has no headroom.")
    if commitment_headroom is not None and commitment_headroom <= 0:
        raise ApiError("ERR_COMMITMENT_CAPACITY_EXCEEDED",
                       "The named commitment has no remaining capacity.")

    return provisional, final, capped
