"""PFOF venue routing (PRD §3.4, SCAFFOLD pfof_routing).

Highest rebate wins; ties break lexicographically ascending. EQUITY uses all
three venues; OPTION uses only VENUE_A and VENUE_B."""
import constants


def select_venue(instrument_type):
    candidates = (constants.OPTION_VENUES if instrument_type == "OPTION"
                  else constants.EQUITY_VENUES)
    # rank by rebate desc, then venue name asc
    best = sorted(candidates, key=lambda v: (-constants.VENUE_REBATE_BPS[v], v))
    return best[0]
