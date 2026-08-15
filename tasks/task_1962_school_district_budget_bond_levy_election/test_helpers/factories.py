"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import FY_A_PAYLOAD, REVENUE_ESTIMATE_DEFAULT


def create_fiscal_year_payload(**overrides) -> dict:
    defaults = dict(FY_A_PAYLOAD)
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_projection_payload(grade_band="ELEMENTARY", projected_pupils=1200,
                              **overrides) -> dict:
    defaults = {"grade_band": grade_band, "projected_pupils": projected_pupils}
    defaults.update(overrides)
    return defaults


def certify_projection_payload(actual_pupils=1250, **overrides) -> dict:
    defaults = {"actual_pupils": actual_pupils}
    defaults.update(overrides)
    return defaults


def create_budget_version_payload(expected_fiscal_year_version, **overrides) -> dict:
    defaults = {"expected_fiscal_year_version": expected_fiscal_year_version}
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(fund_code="EDUCATION", function_code="1100",
                               object_code="100", cost_center="DISTRICT",
                               appropriation_amount=1000, **overrides) -> dict:
    defaults = {
        "fund_code": fund_code,
        "function_code": function_code,
        "object_code": object_code,
        "cost_center": cost_center,
        "appropriation_amount": appropriation_amount,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(from_line_id, to_line_id, amount, **overrides) -> dict:
    defaults = {"from_line_id": from_line_id, "to_line_id": to_line_id,
                "amount": amount}
    defaults.update(overrides)
    return defaults


def create_staffing_allocation_payload(grade_band, enrollment_projection_id,
                                       allocated_fte, **overrides) -> dict:
    defaults = {
        "grade_band": grade_band,
        "enrollment_projection_id": enrollment_projection_id,
        "allocated_fte": allocated_fte,
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(title="Teacher 1", fte=1.0, base_salary=64000,
                            **overrides) -> dict:
    defaults = {"title": title, "fte": fte, "base_salary": base_salary}
    defaults.update(overrides)
    return defaults


def fill_position_payload(incumbent_salary=65000, **overrides) -> dict:
    defaults = {"incumbent_salary": incumbent_salary}
    defaults.update(overrides)
    return defaults


def create_revenue_estimate_payload(**overrides) -> dict:
    defaults = dict(REVENUE_ESTIMATE_DEFAULT)
    defaults.update(overrides)
    return defaults


def create_hearing_payload(venue="BOARD_ROOM", hearing_date="2027-03-20",
                           **overrides) -> dict:
    defaults = {"venue": venue, "hearing_date": hearing_date}
    defaults.update(overrides)
    return defaults


def create_election_payload(election_date="2027-11-02", election_type="REGULAR",
                            **overrides) -> dict:
    defaults = {"election_date": election_date, "election_type": election_type}
    defaults.update(overrides)
    return defaults


def canvass_payload(results) -> dict:
    return {"results": results}


def canvass_result_entry(ballot_measure_id, yes_votes, no_votes) -> dict:
    return {"ballot_measure_id": ballot_measure_id,
            "yes_votes": yes_votes, "no_votes": no_votes}


def create_bond_proposal_payload(question_title="Bond Question A",
                                 purpose="Capital improvements",
                                 total_amount=18000000, **overrides) -> dict:
    defaults = {"question_title": question_title, "purpose": purpose,
                "total_amount": total_amount}
    defaults.update(overrides)
    return defaults


def create_bond_project_payload(name="Roof Replacement", site_code="HS-01",
                                estimated_cost=6000000,
                                construction_start="2028-06-01",
                                construction_end="2028-08-15",
                                priority_rank=1, **overrides) -> dict:
    defaults = {
        "name": name,
        "site_code": site_code,
        "estimated_cost": estimated_cost,
        "construction_start": construction_start,
        "construction_end": construction_end,
        "priority_rank": priority_rank,
    }
    defaults.update(overrides)
    return defaults


def create_ballot_measure_payload(bond_proposal_id,
                                  ballot_language="Shall the District issue "
                                                  "bonds for capital "
                                                  "improvements",
                                  **overrides) -> dict:
    defaults = {"bond_proposal_id": bond_proposal_id,
                "ballot_language": ballot_language}
    defaults.update(overrides)
    return defaults


def ballot_language_of_length(word_count: int) -> str:
    """Exactly `word_count` whitespace-separated tokens (§3.7 word_count)."""
    return " ".join(f"w{i:03d}" for i in range(1, word_count + 1))


def create_publication_payload(publication_type="FACTUAL",
                               content="Bond fact sheet", **overrides) -> dict:
    defaults = {"publication_type": publication_type, "content": content}
    defaults.update(overrides)
    return defaults


def create_bond_sale_payload(series_label="2027-A", par_amount=10000000,
                             premium=150000, issuance_costs=80000,
                             sale_date="2027-12-01",
                             expected_bond_proposal_version=None,
                             **overrides) -> dict:
    defaults = {
        "series_label": series_label,
        "par_amount": par_amount,
        "premium": premium,
        "issuance_costs": issuance_costs,
        "sale_date": sale_date,
    }
    if expected_bond_proposal_version is not None:
        defaults["expected_bond_proposal_version"] = expected_bond_proposal_version
    defaults.update(overrides)
    return defaults


def create_expenditure_payload(vendor_name="Roofing Co", amount=1000000,
                               description="roof tear-off", **overrides) -> dict:
    defaults = {"vendor_name": vendor_name, "amount": amount,
                "description": description}
    defaults.update(overrides)
    return defaults


def review_payload(approved=True) -> dict:
    return {"approved": approved}


def create_amendment_payload(reason="Reallocate between projects",
                             adjustments=(), **overrides) -> dict:
    defaults = {"reason": reason, "adjustments": list(adjustments)}
    defaults.update(overrides)
    return defaults


def amendment_adjustment(bond_project_id, delta_authorized) -> dict:
    return {"bond_project_id": bond_project_id,
            "delta_authorized": delta_authorized}
