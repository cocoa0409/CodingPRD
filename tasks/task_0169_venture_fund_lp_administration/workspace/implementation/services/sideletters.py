"""Side-letter term lookups (PRD §3.7).

Only an EXECUTED side letter excuses an LP from a call purpose or discounts
that LP's fee. When MFN ranks could conflict, a lower mfn_rank takes
precedence; we resolve by lowest mfn_rank among the LP's EXECUTED letters on
the fund.
"""
import db


def _executed_letters(fund_id, lp_id):
    letters = [
        sl
        for sl in db.side_letters.values()
        if sl["fund_id"] == fund_id
        and sl["lp_id"] == lp_id
        and sl["status"] == "EXECUTED"
    ]
    # Lower mfn_rank takes precedence when terms conflict.
    letters.sort(key=lambda sl: (sl["mfn_rank"], sl["created_at"]))
    return letters


def lp_excused(lp_id, fund_id, purpose):
    """True when the LP holds an EXECUTED side letter excusing this purpose."""
    for sl in _executed_letters(fund_id, lp_id):
        if purpose in sl.get("excused_purposes", []):
            return True
    return False


def sideletter_discount_bps(lp_id, fund_id):
    """The fee_discount_bps from the LP's executed side letter on the fund.

    When multiple executed letters exist, the lowest-mfn_rank one takes
    precedence.
    """
    letters = _executed_letters(fund_id, lp_id)
    if not letters:
        return 0
    return letters[0]["fee_discount_bps"]
