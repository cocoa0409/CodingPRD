# Task 0078 ESPP Stock Purchase — STEP 7 Summary

## Result
All 8 parallel rounds pass: 70/70 tests each round (final sweep clean).

## Iterations run
2 full 8-round parallel sweeps (1 baseline, 1 final verification), plus 1
single authoritative confirmation run between them.

## Failures diagnosed (union across baseline 8-round sweep)
Three tests failed identically in all 8 baseline rounds:
1. `test_create_participant_returns_201_with_fields` (test_20_entities.py) —
   `AssertionError: id must be a UUID: 'ec1a167cadf4495b8676661fbca72f53'`
2. `test_per_share_price_rounds_half_up_via_share_lot_consistency`
   (test_02_combinatorial_formula.py) — `NameError: name 'admin_headers' is not defined`
3. `test_form3922_computed_read_boxes` (test_24_endpoints.py) —
   `Expected 201, got 409: ERR_FORM_ALREADY_ISSUED`

## Tests deleted
None. All three failing tests trace to verbatim PRD sentences and are uniquely
derivable.

## Fixes applied to test_suite/
- `test_suite/test_02_combinatorial_formula.py`,
  `test_per_share_price_rounds_half_up_via_share_lot_consistency`
  (STEP 2 test-code bug): the function body referenced the `admin_headers`
  fixture (line: `api.get_purchase(ctx["purchase"]["id"], admin_headers)`) but the
  function signature did not declare it, so pytest never injected it and the test
  raised `NameError` before reaching any assertion. Added `admin_headers` to the
  signature (`def ...(api, admin_headers):`), matching its sibling
  `test_per_share_price_rounds_half_up`. The PRD §3.5 / §2.5 assertion itself was
  already correct (199999... actually 999*85/100 = 849.15 -> half-up 849), so only
  the fixture wiring needed fixing — the fix makes the test runnable, not weaker.

- `test_suite/test_24_endpoints.py`, `test_form3922_computed_read_boxes`
  (STEP 2 test-vs-PRD consistency): the test verifies the PRD §3.5 box-value rule
  (box3/box4/box5/box6/tax_year), which is verbatim-covered and uniquely derivable.
  But it obtained the form by POSTing `issue_form_3922` expecting 201. PRD §3.5
  states the run-purchase already creates a Form 3922 ("Alongside each purchase,
  the system creates a ShareLot ... and a Form3922 capturing the tax paperwork")
  and that "a purchase may have its Form 3922 issued only once; a second issuance
  ... is rejected with ERR_FORM_ALREADY_ISSUED". The PRD-faithful implementation
  therefore correctly returned 409. (The sibling test
  `test_form3922_already_issued_conditional` relies on exactly this run-creates-form
  behavior.) Fixed the test to READ the run-created form via
  `api.list_forms_for_purchase(purchase_id, officer)` and assert the box values on
  it. This makes the test more faithful to PRD §3.5, not less.

## Fixes applied to implementation/
- `workspace/implementation/app.py`, `new_id()`:
  Changed `uuid.uuid4().hex` to `str(uuid.uuid4())`. PRD §2.4 requires every
  resource id to be "a UUID with no type prefix"; the runner's `is_valid_uuid`
  checker (used by `assert_participant` and every entity assertion) requires the
  canonical dashed UUID form. The `.hex` variant stripped the dashes and failed the
  format check across all entities. `new_id()` is the sole id-minting site, so this
  one change fixes ids for participants, plans, offerings, purchase periods,
  enrollments, contributions, purchases, share lots, dispositions, forms, and
  accrual ledgers.

## Note on session output reliability
The Bash stdout channel returned empty intermittently during this session; results
were verified by having Python write summaries to files and reading those files.
The authoritative artifacts are the eight `results.{1..8}.json` from the final
sweep, all of which report passed == total == 70.
