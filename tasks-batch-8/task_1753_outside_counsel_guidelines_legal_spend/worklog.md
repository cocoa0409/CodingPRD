# Worklog — task_1753_outside_counsel_guidelines_legal_spend

## Step 1: Create Task Directory — 2026-08-14T13:29:00.000Z

Task directory `tasks/task_1753_outside_counsel_guidelines_legal_spend/` and `workspace/` subdirectory pre-created and pre-assigned by the pipeline launcher. No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T13:56:00.000Z

Subagent completed after an internal redesign: switched the API from nested to a **flat URL topology** (`api_prefix: /`) because the skill's FK reverse-reachability linter derives entity collection segments only from 2-segment single-resource GETs (`GET /<collection>/{id}`) — nested paths like `/legal-departments/{deptId}/matters/{matterId}` could never satisfy it. Final design: flat single-GETs + flat list GETs with FK filters (`GET /matters?legal_department_id=&panel_firm_id=`), action-style mutations (`POST /matters/{id}/engage`, `POST /invoices/{id}/pay`, …), FK fields carried in create bodies.

Artifacts written (all YAML-validated):
- SCAFFOLD.yaml (1420 lines): 14 entities, 63 endpoints, 22 errors, 9 state machines, 6 calculations, 9 validations, 2 roles, concurrency rules.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1606 lines): 18 non-stub instances across 9 depth rules (dual_variant_calc×2, combinatorial_formula×2, non_linear_state_machine×2, transitive_cascade×2, priority_pair_validation_conflict×2, boundary_precision_check×2, cross_entity_state_dependency×2, resource_temporal_overlap×2, compensating_invariant×2).
- SCAFFOLD_CORNER_DESIGN.yaml (1781 lines): 43 non-stub instances across 9 sections (entities×6, state_machines×8, calculations×5, validations×5, endpoints×2, errors×12, rbac×2, cross_cutting_layers×2, consistency_model×1).

No sibling task_* directories were inspected (hard-constraint honored).

## Step 3: Copy Shared Files — 2026-08-14T13:58:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1753_outside_counsel_guidelines_legal_spend/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T14:10:00.000Z

Subagent summary (verbatim):

All three hard contracts pass. The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1753_outside_counsel_guidelines_legal_spend/workspace/PRD.md` — 302 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Nested Resource Retrieval · 2.7 Monetary Values, Hours, and Rounding · 2.8 Optimistic Concurrency Control · 2.9 Validation Pipeline and Priority Order · 2.10 Hierarchical Consistency and Cascading Effects
- §3 Business Logic: 3.1 Department Configuration & Panel Firm Lifecycle · 3.2 Guideline Publication & Acknowledgment · 3.3 Matter Engagement · 3.4 Timekeepers & Rate Card Cycle · 3.5 Invoice Submission & Automated Rule Enforcement · 3.6 Manual Review, Corrections & Appeals · 3.7 Accruals, Forecasts & Scorecards
- §4 Endpoint Definitions (63-row table, 4 columns) · §5 Error Code Catalogue (22-row table, 2 columns)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 86 required identifiers (14 entities' fields + endpoint inputs + query/path params + response-only fields) — 86 present, 0 missing. **PASS** (2 passes; pass 1 surfaced `invoice_id`, repaired in §3.5)
- Contract 2 (Rule Coverage): 9 validations (priority ladder explicit in §2.9) · 2 OCC rules (`expected_matter_version`/`expected_panel_firm_version` + `ERR_STALE_VERSION`/412, in §2.8 and §3.4/3.5) · 30 state transitions across 9 machines (all preconditions paired with error ids, all cascade hops stated) · 6 calculations (per-line round-half-up pinning, sub-cap 80%/60% factors, floor ceiling, prior-card tie-break, block-billing regex translated to prose, staffing-ratio 4-decimal + inclusive boundary, forecast pinned evaluation order, scorecard 30/30/20/20 weights with inversions and 12-month window) · all endpoint side effects and `applies_to` scopes expressed · sibling branches (offboard's 3 cascades, grant/deny, pay-from-APPROVED vs PARTIALLY_APPROVED, rule-engine steps a–e) rendered at equal density. **PASS**
- Contract 3 (§3 Path Purity): 357 backtick tokens scanned — 0 paths, 0 bare HTTP methods, 0 method+path combos. All endpoints referenced via state-pair framing, role+verb, or capability description. **PASS**

**Coverage audit:** All 14 entities, 9 state machines, 6 calculations, 9 validations, 22 errors, 2 roles (with identity translation — `LegalOpsReviewer` opaque, `PanelFirmUser` entity-backed by `PanelFirm`), 2 concurrency rules, and 63 endpoints translated into prose.

**Deliberate scattering / Zero-Silence decisions:** department policy knobs introduced in §3.1 then re-used where they bite (`guideline_notice_days` in §3.2, sub-caps in §3.4, ratio band in §3.5); OCC fields specified in §2.8 and re-narrated at each guarded write; invoice payload split between §3.5 (core) and §2.8 (version field); suspension two-hop auto-deny cascade fully spelled (`AUTO_DENIED_FIRM_SUSPENDED` note + line flip + total recompute); provisional-vs-final payable divergence stated explicitly; the headcount staffing variant placed in §3.3 away from the billed-hours enforcement in §3.5; `ERR_OVER_BUDGET`/`BILLED_HOURS` explicitly named after second-pass repair. The two withheld design files were never opened.

## Step 6: Generate Implementation — 2026-08-14T14:38:00.000Z

Subagent summary (verbatim):

63 routes implemented vs 63 in the scaffold, no seeding (the only "seed" match is a docstring). Implementation complete.

**Files written** (all under `workspace/implementation/`):
- `start.sh` — executable, guarded `pip install` (skips when flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — flask only
- `app.py` — entry point, blueprint registration, `ApiError`/404/405/500 handlers
- `db.py` — in-memory stores (start empty on boot, no seeding), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), UUID ids, `req_` request ids, ISO-8601 3-fractional-digit timestamps, `base_resource`/`touch` (version+updated_at on every mutation)
- `errors.py` — all 22 catalog error IDs with exact HTTP statuses
- `response.py` — `meta`/`response_type`/`data` envelope, error envelope (`error_id`/`message`), `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp 1–100, offset≥0), created_at-ascending sort
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED` → 403 `ERR_FORBIDDEN` priority order)
- `helpers.py` — left-to-right nested path resolvers (404 `ERR_NOT_FOUND` at first unresolved id), query filters
- `routes/`: departments.py, panel_firms.py, guidelines.py, matters.py, rate_cards.py, timekeepers.py, invoices.py, accruals.py, scorecards.py, clock.py
- `services/invoice_service.py` — rule engine, aggregation, booking, accrual matching, forecast recompute, overdue-ack sweep

**Endpoint coverage: 63/63** routes implemented (verified by count against scaffold).

**State machines:** all 8 implemented with preconditions and cascades — PanelFirm (incl. 2-hop suspend auto-deny cascade and guarded offboard cascade), GuidelineVersion (publish w/ overlap + notice-gap guards, supersede + ack cascade-create), GuidelineAcknowledgment (PENDING/OVERDUE→ACKNOWLEDGED, clock sweep), Matter (engage w/ ack gate, close guards, reopen), RateCard (submit/approve/reject/revise incl. supersession), Timekeeper (qualify/disqualify with pending-lines guard), Invoice (auto SUBMITTED→UNDER_REVIEW, aggregate derivation, pay freeze, void), InvoiceLineItem (approve/adjust/reject incl. post-approval compensating debit, REINSTATED/UPHELD via appeals), Appeal (claim/grant 3-hop credit/deny 2-hop).

**Calculations:** per-line `round_half_up(hours*rate_cents)` pinned before aggregation; approved/final payable (final frozen at PAID); annual rate increase with class sub-caps (PARTNER 100% / ASSOCIATE 80% / PARALEGAL 60% of cap), floor ceiling, prior-card tie-break effective_year DESC/created_at ASC, clamp-don't-block; block-billing regex `L[0-9]{3}` case-sensitive ≥2 distinct; staffing ratio at 4-decimal precision, strict-outside-band violation (boundary inclusive), BILLED_HOURS vs HEADCOUNT bases; forecast pinned order billed→wip→variance; scorecard weighted 0.30/0.30/0.20/0.20 with per-metric 2dp half-up rounding before weighting and trailing-12-month window.

**Validations/errors:** full 9-priority pipeline (auth → forbidden → existence → state → line-level regulatory → referential → uniqueness/window → temporal → fiscal/OCC). Both OCC guards (`expected_matter_version`, `expected_panel_firm_version` → 412 `ERR_STALE_VERSION`). All 22 error IDs wired.

**Smoke test:** server boots cleanly from a fresh process via `bash start.sh` on a free port; a real endpoint (`POST /_clock/set_current_utc` plus department/firm CRUD) responds with the correct envelope. Two end-to-end suites (88 behavioral checks total) pass — publish/ack cascade, overdue sweep + late ack, ack-gated engage, OCC 412s, cap clamping to exact cents (110000/86400/42400), block-billing/rate-exceeds/unqualified rejections, over-budget line rejection, appeal grant compensating credit (matter billed 220000→479200), pay freeze, post-approval compensating debit, void, adjust flow, pagination clamping, and offboard cascades.

## Step 5: Generate Unit Tests — 2026-08-14T14:52:00.000Z

Subagent summary (verbatim):

Generation complete. All artifacts are under `/home/ubuntu/github/CodingPRD/tasks/task_1753_outside_counsel_guidelines_legal_spend/`.

## Files written

**test_helpers/ (9 files)**
- `types.py` — 14 entity TypedDicts + 10 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (52 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 22 `ApiErrorId`s with §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (14) + `assert_matter_spend_invariants`
- `factories.py`, `constants.py` (sub-cap factors 1.0/0.8/0.6, scorecard weights, clock default), `test_users.py` (`TEST_USERS` + mandatory `make_panel_firm_headers(firm_id)` builder for the entity-backed role)
- `fixtures.py` — composite setups: `setup_billing_ready` (dept→firm→qualified TK→approved card→engaged matter), `setup_partially_approved_invoice`, `setup_rejected_invoice_with_claimed_appeal`, `publish_guideline_and_get_ack`, OCC-fresh rate-card creation, line factories (`clean_line`/`block_billed_line`/`rate_not_on_card_line`), appeal/accrual/forecast helpers. All ownership-gated calls thread `firm["id"]`.

**test_suite/ (10 files, 71 tests)** — `conftest.py` + `test_01`…`test_09` grouped by concern (creation/envelope, guidelines/acks, matters, rate cards/timekeepers, invoice auto-review, line review/corrections, appeals/payment, firm cascades, accruals/forecasts/staffing).

## Test counts per queue
- **Queue A (Difficulty): 37 tests across all 18 instances** (≥2 each; the invoice branching-fork instance got 3, one per branch)
- **Queue B (Corner): 34 tests across 34 of 35 non-stub instances**; all 8 `excluded_because:` stubs verified to resolve to real queue-A instances and were not translated

## Skipped instances (two-condition verdicts)
1. **Corner/calculations/scorecard_weighted_score_literal** — SKIP. Coverage fails: PRD §3.7 defines the four metrics and weighting but never states an empty-history default of 100 per metric. Unique derivability fails: with zero history a PRD-only reader could emit 0, 100, or null per metric; `overall == 100.00` is not uniquely derivable. (The only skip in either queue.)

Judgment calls (emitted, weakest-safe form): `timekeeper_invalid_tk_class_rejected` and `matter_creation_missing_required_field` assert 4xx + error envelope only (PRD names no specific error_id for body-schema rejections, so no error_id is asserted). In `forecast_evaluation_order_breaks_circle` I added a `set_clock` to 2026-09-15 before filing the 2026-09 accrual — the literal recipe would otherwise hit PRD §3.7's future-period rejection under the 2026-08-01 default clock; asserted values are unchanged.

## Stage 2 self-audit results
- **Tag integrity:** 71/71 test functions carry exactly one `Design:` line; every tag resolves verbatim to a `name:` in the source yaml; no untagged/dual-tagged tests (programmatic check)
- **Coverage:** no shortfalls — 18/18 difficulty instances ≥2 tests, 34/34 emitted corner instances ≥1 test
- **PRD citations:** 115 quoted citations across the suite; all verbatim-match PRD.md under whitespace-normalized grep (C1/C2/C3)
- **Helper coverage:** `test_helpers` imports cleanly against the real framework; every `from test_helpers import …` name in the suite resolves; all fixture callables present
- **Hygiene:** all files compile; zero `skip`/`skipif`/`xfail` markers; no scaffold/section-table references in generated code

## Step 7: Run Tests and Iterate — 2026-08-14T15:05:00.000Z

Subagent summary (verbatim):

All 8 rounds pass 71/71. The sweep is clean.

- **Iterations run**: 2 (initial sweep surfaced 4 deterministic failures; fixed, then re-ran the full 8-round parallel sweep — all 8 rounds now report 71/71 passed, 0 failed, 0 errors).

- **Tests deleted**: none. Every failing test traced to a verbatim PRD rule with unique derivability; all four failures were test-side bugs.

- **Fixes applied to `test_suite/`** (no `test_helpers/` changes were needed; fixtures/factories/role-headers were all PRD-faithful):
  1. `test_04_rate_cards_and_timekeepers.py::test_error_stale_version_on_rate_card_create` — the setup's first `create_rate_card` was wrapped in `validate_success(resp)` which defaults to expecting HTTP 200, but PRD §2.4 ("Newly created resources return `201 Created`") and §4 mandate 201. Added the explicit `201` expected status. The implementation was correct.
  2. `test_09_accruals_forecasts_and_staffing.py::TestForecastEvaluationOrder._setup_partial_match` (covers `test_forecast_wip_and_variance_after_partial_match` and `test_matter_spend_counters_after_partial_match`) — the fixture captured `ctx["matter_version"]` before creating two accruals, but accrual creation mutates the matter's `accrual_outstanding_cents` (PRD §3.7), which per PRD §2.4 increments the matter's `version`; the subsequent OCC-guarded invoice submission was then correctly rejected with `ERR_STALE_VERSION` (§2.8). Fixed the fixture to re-read the matter version via `get_matter(...)` after accrual creation.
  3. `test_09_accruals_forecasts_and_staffing.py::test_accrual_matched_by_invoice_in_period` — same stale-version-after-accrual-creation test bug; re-reads the matter version before `submit_invoice`.

- **Fixes applied to `implementation/`**: none. The implementation was PRD-faithful in all four failure cases (201 on create; matter version bump on accrual mutation; ERR_STALE_VERSION on replayed OCC version). Storage is in-memory dicts only with no seeding, and `start.sh` re-invocation gives a fresh boot per test.

## Step 8: Finalize PRD — 2026-08-14T15:12:00.000Z

Subagent summary (verbatim):

All verification is complete. `PRD_FINALIZED.md` has been produced and is byte-identical to `PRD.md` — the correct minimal patch is the **empty patch**, because every step_7_diff item was a pure test-side bug against a verbatim, uniquely-derivable PRD rule, with zero implementation fixes.

**Line counts / delta**: PRD.md = 301 lines; PRD_FINALIZED.md = 301 lines; 0.0% delta (`diff` confirms IDENTICAL).

**Changes**: none — no edits were warranted.

### Per-item analysis of `<step_7_diff>`

1. **`test_04...::test_error_stale_version_on_rate_card_create`** (test fix: added explicit `201` to `validate_success`) — Pure fixture bug. Implementation returns 201 on rate-card creation (`implementation/routes/rate_cards.py:41`). PRD §2.4 ("Newly created resources return `201 Created`") and §4 (rate card explicitly in the 201 list) already uniquely determine this. No PRD silence, no mismatch → no edit.

2. **`test_09...::TestForecastEvaluationOrder._setup_partial_match`** (test fix: re-read matter version after accrual creation) — Pure fixture bug. Implementation adds `amount_cents` to `matter["accrual_outstanding_cents"]` and calls `db.touch(matter)`, which increments `version` (`implementation/routes/accruals.py:52-53`, `implementation/db.py:136-139`). The chain PRD §3.7 ("Creation adds the accrual's `amount_cents` to the matter's `accrual_outstanding_cents`") + §2.4 ("increments by one on every mutation, including mutations caused by cascades and derived-field recomputation") + §2.8 (`ERR_STALE_VERSION` on mismatch) uniquely derives the version bump and the rejection. No PRD silence → no edit.

3. **`test_09...::test_accrual_matched_by_invoice_in_period`** (test fix: same re-read) — Identical chain to item 2. No edit.

### Pre-edit search log (verification searches performed per candidate subject; all concluded "no edit needed")

- **(a) Subject: HTTP status on resource creation.** (b) Enumerated/read: `implementation/routes/rate_cards.py:17-41` (201 on create), grep for `201` across routes (creation endpoints return 201; e.g. `accruals.py:55` also 201), PRD §2.4 and §4. (c) No wording change — PRD verbatim already pins 201 for all creations including rate cards; impl matches everywhere checked.
- **(a) Subject: matter `version` increment on accrual creation.** (b) Enumerated/read: `implementation/routes/accruals.py:44-55` (mutates `accrual_outstanding_cents`, `db.touch(matter)`), `implementation/db.py:121-139` (`base_resource` starts `version:1`; `touch` bumps `version` + refreshes `updated_at`), PRD §2.4, §3.7, §2.10. (c) No wording change — §2.4's "every mutation, including … derived-field recomputation" plus §3.7's explicit counter mutation already cover this path and all other `touch` callsites.
- **(a) Subject: OCC stale-version rejection.** (b) Enumerated/read: `implementation/routes/invoices.py:64-72` (`expected_matter_version` → `errors.stale_version()`), `implementation/routes/rate_cards.py:25-31` (`expected_panel_firm_version`, including non-integer → stale), PRD §2.8, §2.9 step 9. (c) No wording change — §2.8 pins both guarded endpoints and the 412 rejection; impl is faithful, and no other endpoint accepts a version field, matching "No other endpoint accepts a version field."

## Step 9: Complete PRD — 2026-08-14T15:35:00.000Z

Subagent summary (verbatim):

Done. PRD_COMPLETED.md is produced at `workspace/PRD_COMPLETED.md`, a minimal patch over PRD_FINALIZED.md with all changes inline (no new sections; +2 net lines).

**Source vs output:** PRD_FINALIZED.md = 301 lines / 46,215 chars → PRD_COMPLETED.md = 303 lines / 51,537 chars (char delta +5,269; 24 diff hunks, all in-paragraph inserts/revisions except one 2-line insert in §2.2).

**Counts:** 25 ambiguity-pins, 7 mismatch-revisions.

**Mismatch revisions (PRD described behavior impl does not exhibit):**
- §2.8 — revise — mismatch — invoice OCC: `expected_matter_version` is optional (checked only when supplied), not required — `implementation/routes/invoices.py:64-72`
- §2.9 intro — revise — mismatch — added carve-out that endpoint-specific guard order in §3 governs over the generic ladder, because publish evaluates temporal before overlap/notice-gap (ladder says 7 before 8) — `implementation/routes/guidelines.py:56-81`
- §2.9 step 5 — revise — mismatch — auto-review controls are block-billing, rate-exceeds, unapproved-timekeeper; staffing-ratio enforcement does not exist in auto-review — `implementation/services/invoice_service.py:146-180`
- §3.1 — revise — mismatch — suspension blocks new invoices and rate-card *submission*; draft rate-card creation is not blocked — `implementation/routes/rate_cards.py:18-41` (no ACTIVE check) vs `:70-71`
- §3.5 — revise — mismatch — submission guard order corrected to impl/§2.9-ladder order: referential (timekeeper) before uniqueness before temporal — `implementation/routes/invoices.py:37-72`
- §3.5 — revise — mismatch — only the budget-gate overlay runs in auto-review; staffing ratio is advisory-only (§3.3 read) plus a manual rejection reason; budget-gate mechanics pinned (submission-order running total, strict `>`, rejected line's amount not accumulated) — `implementation/routes/invoices.py:115-127`
- §3.6 — revise — mismatch — voiding a REJECTED invoice "closes the matter of record" → touches nothing else; matter state/counters untouched — `implementation/routes/invoices.py:176-186`

**Ambiguity pins (PRD silent, impl behavior now pinned):**
- §2.1 — insert — ambiguity — empty header value counts as missing → `ERR_UNAUTHENTICATED` — `implementation/middleware.py:22`
- §2.2 — insert — ambiguity — missing required field / bad value-domain values → `ERR_REFERENTIAL_INTEGRITY` 422 catch-all; other values unvalidated — `implementation/helpers.py:20-33`
- §2.3 — insert — ambiguity — pagination clamping (limit 1–100, offset ≥ 0; non-numeric → defaults) — `implementation/response.py:57-79`
- §2.3 — insert — ambiguity — sort ties break by insertion order — `implementation/response.py:82-87`
- §2.3 — insert — ambiguity — `has_more` = (`offset`+`limit`) < `total_count` — `implementation/response.py:23`
- §2.5 — insert — ambiguity — clock set to exactly the supplied instant (no monotonicity guard); unparseable `to_iso8601` → `ERR_INVALID_TEMPORAL` — `implementation/routes/clock.py:19-23`
- §3.2 — insert — ambiguity — publication stamps `published_at` with the logical clock — `implementation/routes/guidelines.py:84`
- §3.2 — insert — ambiguity — publish guards evaluated in the order stated — `implementation/routes/guidelines.py:56-81`
- §3.3 — insert — ambiguity — matter creation requires `panel_firm_id` resolvable within the department (`ERR_REFERENTIAL_INTEGRITY`); no firm-status precondition — `implementation/routes/matters.py:23-25`
- §3.3 — insert — ambiguity — staffing `basis` case-insensitive, non-HEADCOUNT falls back to billed-hours; uncomputable share → `partner_share_pct` null and `compliant` true — `implementation/routes/matters.py:138-165`
- §3.4 — insert — ambiguity — timekeeper registration: firm-ownership check (`ERR_FIRM_MISMATCH`) and invalid `tk_class` → `ERR_REFERENTIAL_INTEGRITY` — `implementation/routes/timekeepers.py:18-24`
- §3.4 — insert — ambiguity — rate-card creation: firm-ownership check; non-integer `expected_panel_firm_version` → `ERR_STALE_VERSION` — `implementation/routes/rate_cards.py:21-31`
- §3.4 — insert — ambiguity — rate rows: ownership + timekeeper referential checks, duplicate rows allowed, `approved_rate_cents` null until approval — `implementation/routes/rate_cards.py:185-205`
- §3.5 — insert — ambiguity — `line_items` may be empty or omitted — `implementation/routes/invoices.py:46`
- §3.5 — insert — ambiguity — billing-period year taken from `billing_period_start` — `implementation/routes/invoices.py:88`
- §3.5 — insert — ambiguity — covering rate card = exact-year APPROVED card else most recent earlier (ties: ascending creation); no card/row → rate checks skipped, qualified line approved — `implementation/services/invoice_service.py:125-143,163-179`
- §3.5 — insert — ambiguity — empty invoice derives to `PARTIALLY_APPROVED` — `implementation/services/invoice_service.py:70-78`
- §3.5 — insert — ambiguity — spend books only on transition from a non-booked state; re-derivation within booked states never double-books — `implementation/services/invoice_service.py:216-219`
- §3.5 — insert — ambiguity — accrual matching compares the period as the first instant of its month against [`billing_period_start`, `billing_period_end`) — `implementation/services/invoice_service.py:183-206`
- §3.6 — insert — ambiguity — manual reject: reason optional (null); unrecognized reason → `ERR_REFERENTIAL_INTEGRITY` — `implementation/routes/invoices.py:276-278`
- §3.6 — insert — ambiguity — appeal filing requires firm match (`ERR_FIRM_MISMATCH`); concurrent appeals on one line allowed — `implementation/routes/invoices.py:300-317`
- §3.6 — insert — ambiguity — `resolution_note` optional on grant/deny — `implementation/routes/invoices.py:355-358,382-385`
- §3.6 — insert — ambiguity — grant credit is unconditional and stacks with the §3.5 booking when the grant lands an unbooked invoice on an approval state — `implementation/routes/invoices.py:366-370`
- §3.6 — insert — ambiguity — paying from any state other than APPROVED/PARTIALLY_APPROVED → `ERR_INVALID_STATE` — `implementation/routes/invoices.py:161-162`
- §3.7 — insert — ambiguity — accrual firm-ownership check; `period_month` outside 1–12 or non-integer period → `ERR_INVALID_TEMPORAL` — `implementation/routes/accruals.py:21-30`
- §3.7 — insert — ambiguity — duplicate unmatched accruals for the same period allowed — `implementation/routes/accruals.py:36-43`
- §3.7 — insert — ambiguity — forecast read before any write → `ERR_NOT_FOUND`; full recompute trigger list incl. reads, each refresh bumping `version` — `implementation/routes/accruals.py:102-110`, `implementation/services/invoice_service.py:224-241`
- §3.7 — insert — ambiguity — scorecard window: opens one year before clock (day clamped, same time of day), inclusive both ends; empty-denominator metrics compute as zero — `implementation/routes/scorecards.py:21-27,57-59,77,85,93,112`
- §3.7 — insert — ambiguity — firm's `scorecard_overall_pct` null until first snapshot persists — `implementation/routes/panel_firms.py:25`, `implementation/routes/scorecards.py:139-141`

Key finding: the largest substantive divergence was the staffing-ratio rule — the PRD described it as an auto-review enforcement overlay, but the implementation only ever exposes it via the advisory `staffing-ratio` endpoint and as a manual rejection reason; the PRD was revised to match.
