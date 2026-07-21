"""Grading (first-edition determination) and appraisal valuation variants + OCC."""
from test_helpers import (
    validate_success, validate_error,
    create_appraisal_payload, TEST_USERS,
)
from test_helpers.fixtures import make_graded_book, issue_appraisal

MANAGER = TEST_USERS["manager_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


def test_first_edition_true_printing_1_stated(api):
    """PRD §3.3: "A stated first edition with printing number 1 is therefore a first
    edition; the same book stated at printing number 2 is not."

    Design: Corner/calculations/first_edition_true_when_printing_1_and_stated
    """
    ctx = make_graded_book(condition_grade="FINE", comp_median_cents=50000,
                           printing_number=1, stated_first_edition=True, title="Ulysses 1922")
    book = ctx["book"]
    assert book["is_first_edition"] is True
    assert book["condition_grade"] == "FINE"


def test_first_edition_false_printing_2(api):
    """PRD §3.3: "A stated first edition with printing number 1 is therefore a first
    edition; the same book stated at printing number 2 is not."

    Design: Corner/calculations/first_edition_false_when_printing_2
    """
    ctx = make_graded_book(condition_grade="FINE", comp_median_cents=50000,
                           printing_number=2, stated_first_edition=True, title="Ulysses 2pr")
    assert ctx["book"]["is_first_edition"] is False


def test_grade_already_graded_item_rejected(api):
    """PRD §3.3: "Grading is an `Appraiser` action available only while a book is in
    `INTAKE`; attempting it in any other state is rejected with `ERR_ITEM_NOT_GRADED`."

    Design: Corner/state_machines/grade_twice_returns_409
    """
    ctx = make_graded_book(condition_grade="GOOD", comp_median_cents=2500, title="Eveline")
    res = api.grade_book_item(ctx["book"]["id"], {"condition_grade": "FINE"}, APPRAISER)
    validate_error(res, "ERR_ITEM_NOT_GRADED", expected_status=409)


def test_appraisal_fair_market_and_retail_variants(api):
    """PRD §3.3: "The `fair_market_value_cents` is the comparable base multiplied by
    the condition multiplier and by the premium factor, rounded half up to whole
    cents. The `retail_replacement_value_cents` is the same product additionally
    multiplied by a retail markup of 1.6, rounded half up to whole cents; because the
    markup exceeds one, the retail variant is strictly larger than the fair-market
    variant for positive inputs."

    Design: Difficulty/dual_variant_calc/appraisal_fair_market_vs_retail_replacement
    """
    ctx = make_graded_book(condition_grade="FINE", comp_median_cents=10000,
                           printing_number=1, stated_first_edition=True, title="Ulysses")
    appraisal = issue_appraisal(ctx["book"]["id"], ctx["book"]["version"], basis="FAIR_MARKET")
    assert appraisal["fair_market_value_cents"] == 21000
    assert appraisal["retail_replacement_value_cents"] == 33600
    assert appraisal["final_value_cents"] == 21000
    book = validate_success(api.get_book_item(ctx["book"]["id"], MANAGER), 200)
    assert book["appraised_value_cents"] == 21000


def test_appraisal_retail_replacement_basis_selects_retail(api):
    """PRD §3.3: "The `final_value_cents` is set to the fair-market variant when
    `basis` is `FAIR_MARKET`, and to the retail-replacement variant when `basis` is
    `RETAIL_REPLACEMENT`."

    Design: Difficulty/dual_variant_calc/appraisal_fair_market_vs_retail_replacement
    """
    ctx = make_graded_book(condition_grade="FINE", comp_median_cents=10000,
                           printing_number=1, stated_first_edition=True, title="Ulysses")
    appraisal = issue_appraisal(ctx["book"]["id"], ctx["book"]["version"], basis="RETAIL_REPLACEMENT")
    assert appraisal["final_value_cents"] == 33600
    book = validate_success(api.get_book_item(ctx["book"]["id"], MANAGER), 200)
    assert book["appraised_value_cents"] == 33600


def test_appraisal_stale_book_version_rejected(api):
    """PRD §2.6: "Issuing an appraisal against a book item requires
    `expected_book_item_version` to equal that `BookItem`'s current `version`. A new
    appraisal legitimately supersedes the item's prior issued appraisal; if another
    writer has already issued one and advanced the item's `version`, the submitting
    client's view is stale and the create is refused with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/appraisal_create_stale_book_version_returns_412
    """
    ctx = make_graded_book(condition_grade="GOOD", comp_median_cents=4200, title="A Painful Case")
    stale_version = ctx["book"]["version"]
    issue_appraisal(ctx["book"]["id"], stale_version, basis="FAIR_MARKET")
    res = api.create_appraisal(
        ctx["book"]["id"], create_appraisal_payload(stale_version, basis="RETAIL_REPLACEMENT"),
        APPRAISER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
