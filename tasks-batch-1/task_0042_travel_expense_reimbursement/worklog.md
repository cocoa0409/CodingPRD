# Worklog — task_0042_travel_expense_reimbursement

Scenario: Travel & Expense Reimbursement (T&E): GSA Per Diem, flight policy, rental car CDW, meal itemization, receipt OCR, virtual card issuance, Out-of-Policy approval chain, Mileage Reimbursement

## Step 1: Create task directory — 2026-05-29T12:09:27Z

Created `tasks/task_0042_travel_expense_reimbursement/` with `workspace/` subdirectory. Pre-allocated path used directly (no scan/auto-increment).

## Step 2: Generate scaffold — 2026-05-29T12:27:19Z

Everything checks out. All three files are correctly structured, lint is clean, and the design counts meet the spec (9 rules × 2 = 18 difficulty instances; 38 corner instances across 8 sections with 3 stubs cross-referencing named §1.8 instances).

## Summary

Generated all three scaffold artifacts for **task_0042_travel_expense_reimbursement** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0042_travel_expense_reimbursement/`. `scaffold_lint.py` reports **VERDICT: clean lint** (484 calls across §1.8+§1.9 conform to §1.5; all 10 FKs reverse-reachable).

**Complexity profile:** compliance/audit primary + ledger-reconciliation secondary; flat topology; branching state machines; approval-chain RBAC; immediate consistency. Layers: dual-variant calc, cascading side effects, optimistic concurrency, rate/threshold triggers. Difficulty band: Advanced (upper end).

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities:** Traveler, Approver, TravelPolicy, PerDiemRate (immutable, `common_fields:false`), TripRequest, VirtualCard, ExpenseReport, ExpenseLine, Receipt, ApprovalStep.
- **6 state machines:** TravelPolicy (DRAFT→ACTIVE→RETIRED), TripRequest (fork-join PENDING→{AUTO_APPROVED→APPROVED, PENDING_OOP_APPROVAL→APPROVED/DENIED}), VirtualCard (ACTIVE↔FROZEN→CLOSED), ExpenseReport (cyclic DRAFT→SUBMITTED→RETURNED→DRAFT, +APPROVED/REJECTED), Receipt (UPLOADED→OCR_PROCESSED→VERIFIED/DISPUTED→VERIFIED), ApprovalStep (PENDING→APPROVED/REJECTED, ordered chain). 1 concurrency rule (OCC on TripRequest.version for card issuance, 412).
- **10 calculations:** flight tiered cap, CDW cap, mileage (milli-cents), lodging per-diem cap, meal_reimbursement (dual-variant PER_DIEM vs ITEMIZED), per_diem_total (round-per-day-then-sum), report_total (pinned eval order), card_settlement (dual-variant hold vs capture), trip_budget_ledger, trip_requires_oop.
- **16 validations** (ordered, priorities 1–15 incl. 9.5).
- **44 endpoints** (CRUD + filtered-list reverse-reachability GETs + action/decision endpoints).
- **24 error codes.**
- **3 roles:** Traveler (`entity_backed:Traveler`), Approver (`entity_backed:Approver`), FinanceAdmin (`opaque`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, all formula-derived assertions pre-computed as literals (e.g., per-diem rounding divergence 20006 vs 20005, mileage 9179, flight 80%-cap 40000, depth-4 approve cascade, two conserved-quantity invariants).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **38 instances** (35 active + 3 `excluded_because:` stubs citing named §1.8 instances) across 8 claim-guide sections: entities (7), state_machines (7), calculations (5), validations (8), endpoints (3), rbac (4), cross_cutting_complexity_layers (3), consistency_model (1). Every error code (incl. ERR_VALIDATION) is now reachable by at least one test.

One structural note: `api_prefix` is `/` (root) because the flat topology uses top-level collections (`/travelers`, `/trip-requests`, etc.); this is required for the lint's FK-segment derivation to resolve correctly.

## Step 3: Copy shared files — 2026-05-29T12:27:40Z

Copied `./INSTRUCTION.md` → `tasks/task_0042_travel_expense_reimbursement/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-29T12:34:14Z

Generated `workspace/PRD.md` (259 lines) for the Travel Expense Reimbursement API.

**Section list:**
- **1. Introduction** — 3 paragraphs framing the T&E / GSA per-diem / out-of-policy-chain domain
- **2. Global Specifications & System-Wide Principles**: 2.1 RBAC (X-User-ID/Role headers; Traveler/Approver entity-backed, FinanceAdmin opaque), 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning (PerDiemRate carries only id + created_at), 2.5 Monetary Precision and Rounding, 2.6 Ordered Request Validation, 2.7 OCC on Card Issuance, 2.8 Cascading Reconciliation and Consistency, 2.9 FK Resolution Order
- **3. Business Logic & Workflows** (9 subsections): 3.1 Policy/reference-data config, 3.2 Trip request & authorization fork, 3.3 Virtual card issuance & lifecycle, 3.4 Building the report & lines, 3.5 Per-line reimbursement caps, 3.6 Meal reimbursement & report totals, 3.7 Receipts & OCR, 3.8 Submitting & deciding the report (approve/reject/return cascades), 3.9 Out-of-policy approval chain
- **4. Endpoint Definitions** — 4-column table (all 44 endpoints)
- **5. Error Code Catalogue** — 2-column table (all 24 error codes)

**Hard Contracts — all PASS:** Contract 1 (Field-Name Coverage): 60/60 identifiers present. Contract 2 (Rule Coverage): 38 high-risk rule checks verified (OCC, 4-hop approve cascade, 2-hop reject cascade, both meal variants, per_diem_total per-day-then-sum rounding, report_total pinned order, all calc formulas, trip/lodging overlap, validation priority ordering). Contract 3 (§3 Path Purity): 339 tokens scanned, 0 violations.

**Confirmation:** Neither design index (SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml) was read; no sibling task consulted. Generated purely from this task's SCAFFOLD.yaml + doc-generator skill spec.

## Step 5: Generate unit tests — 2026-05-29T12:51:57Z

Generated complete test infrastructure for **task_0042_travel_expense_reimbursement** from the four inputs plus the unit-test-generator spec. Both stages compile, all `test_helpers` imports resolve, all 44 `ApiClient` method references are defined, and all modules import cleanly under a framework stub.

### Files created

**`test_helpers/` (Stage 1) — 9 files**
- `types.py` — role/status enums + entity TypedDicts (PerDiemRate correctly omits `updated_at`/`version` per `common_fields: false`)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD endpoint (44 methods)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + card-balance and trip-budget invariant checkers
- `factories.py` — per-entity payload factories (input fields only)
- `constants.py` — per-diem proration factor, OOP budget multiple, standard policy/rate inputs
- `test_users.py` — opaque FinanceAdmin shared constant + entity-backed `make_traveler_headers`/`make_approver_headers` builders
- `fixtures.py` — composite setup helpers (base env → approved trip → card → reports/lines/receipts/OOP-chain → submitted-report-with-card-line)
- `__init__.py` — barrel export

**`test_suite/` (Stage 2) — 12 files** (`conftest.py` + `test_01`…`test_11`)

### Test counts
- **Total: 71 tests**
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances covered with exactly ≥2 tests each
- **Queue B (Corner): 35 tests** — all 35 non-stub corner instances covered with ≥1 test each

### Stubs (not translated, cross-references verified to resolve)
- `Corner/state_machines/report_returned_to_draft_cycle` → owned by `Difficulty/non_linear_state_machine/report_revision_cycle_returned_to_draft`
- `Corner/calculations/meal_per_diem_vs_itemized_divergence` → owned by `Difficulty/dual_variant_calc/meal_per_diem_vs_itemized_diverge`
- `Corner/cross_cutting_complexity_layers/cascade_partial_when_some_lines_out_of_pocket` → owned by `Difficulty/transitive_cascade/report_approve_lines_card_trip_chain`

### Quality gates verified
- Every test docstring ends with exactly one `Design:` tag resolving to a real instance (no untagged, no dual-tagged).
- All 98 quoted PRD citations are verbatim against `PRD.md`.
- Zero `pytest.mark.skip`/`skipif`/`xfail` markers.
- No instances skipped — every non-stub design instance had verbatim PRD coverage and a uniquely-derivable outcome.

### Key formula verifications baked into literal asserts
Per-diem round-per-day-then-sum (6002+6002+8002=20006), PER_DIEM vs ITEMIZED divergence (20000 vs 15000), late-economy floor(50000×0.80)=40000, mileage 137mi→9179, lodging cap 20000×2=40000, report total 56700, OOP fork at 4-night baseline 224000, card-conservation/trip-budget invariants.

## Step 6: Generate implementation — 2026-05-29T12:51:57Z

Generated a complete Python + Flask implementation for the Travel & Expense Reimbursement (T&E) API at `workspace/implementation/`.

### Files (16)
- `start.sh` — launcher (pip install, then `exec python3 app.py`)
- `requirements.txt` — Flask 3.0.3
- `app.py` — entry point, blueprint registration, error handlers; `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")))`
- `db.py` — in-memory `Store` (one dict per entity), id/timestamp helpers, `base_fields`/`touch` for the identity quartet (PerDiemRate gets id+created_at only)
- `errors.py` — `APIError` + full 24-entry error→HTTP-status catalog
- `response.py` — envelope helpers (`meta`/`response_type`/`data`; `req_` ids; ISO 8601 UTC with 3 fractional digits)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401) and RBAC (403)
- `common.py` — body/field validation, date math, `limit`/`offset` pagination (default 10, 1–100)
- `calc.py` — flight/CDW/mileage/lodging caps, GSA per-diem (75% first/last, round-half-up per day then sum), report total, OOP-budget threshold
- `services.py` — FK lookups, line reimbursable dispatch, card ledger + trip ledger + report-total recomputation
- `routes/` — users, policies, trips, cards, lines, receipts, reports, approval_steps

### Endpoints implemented: 45 (all rows of the PRD §4 / scaffold endpoint table).

### Boot contract confirmed
`start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec`. Storage is in-memory only (dicts keyed by id), the store starts empty on every boot, and nothing is seeded or hardcoded at startup.

## Step 7: Run tests and iterate to PASS — 2026-05-29T13:29:28Z

All clean. The loop is complete — every test passes across all 8 parallel rounds (71/71 each, deterministic, no flakiness).

**Iterations run:** 3 sweeps (initial diagnostic + 2 fix batches). Final state: **all 8 parallel rounds pass 71/71**.

**Root causes (all were test/fixture bugs; the implementation was PRD-faithful throughout — no implementation changes made):** The initial sweep showed 21 failing tests in four clusters, all traceable to test_helpers/test_suite constructing preconditions inconsistent with the PRD.

**Tests deleted:** None. Every failing assertion traced to a verbatim PRD rule and was uniquely derivable; the failures were fixable by correcting the test artifacts to be PRD-faithful.

**Fixes applied to test_helpers/ (`fixtures.py`):**
- Added `add_flight_line_with_receipt` helper — adds a flight line and substantiates it with an upload→OCR→VERIFY receipt (ocr_amount = claimed), because PRD §3.7 requires a VERIFIED receipt for any line whose reimbursable ≥ `receipt_required_threshold_cents` (default 7500) before submit. The original fixtures submitted material 30000+ flight lines with no receipt, which the PRD-faithful server correctly rejected with `ERR_RECEIPT_REQUIRED`.
- `setup_submitted_report_with_card_line` — now (a) uploads a verified receipt for the material flight line before submit, and (b) creates the report under `ITEMIZED` so a no-meal report's `meal_reimbursable_cents` is `min(0, per-diem)=0` (PRD §3.6), isolating the single flight line's contribution that the card-capture/trip-commit cascade assertions check. Under the default `PER_DIEM`, §3.6 mandates the full GSA per-diem total be added regardless of meal lines.
- `setup_submitted_report_out_of_pocket_flight` (unused, fixed for consistency) — uploads a verified receipt before submit.

**Fixes applied to test_suite/:**
- `test_01` — raised `budget_total_cents` from 50000 to 100000 on the two card-hold/capture tests: PRD §3.3 forbids `load_limit_cents` (100000) exceeding the trip's `remaining_budget_cents`.
- `test_11` — lowered `budget_total_cents` from 200000 to 100000 on the two OCC card tests: over the default 2-night CA trip the OOP baseline is 112000, so 200000 was out-of-policy and the trip never reached APPROVED. Also rewrote `test_delete_line_releases_hold`'s 204 check (PRD §4 specifies "204 No Content" empty body → direct `status_code == 204` assertion). Also switched `test_approve_cascade_visible_immediately`'s report to ITEMIZED (no-meal → total 30000).
- `test_04`, `test_05`, `test_09`, `test_10`, `test_11` — replaced `add_flight_line` with `add_flight_line_with_receipt` on tests that submit material flight lines but test something other than the receipt gate. In `test_04`'s budget-conservation tests, also switched reports to ITEMIZED so `total_reimbursable_cents` equals the single flight line.

**Fixes applied to implementation/:** None. The server was already PRD-faithful — including the receipt-required gate, the load≤remaining-budget check, the 204-no-body deletion, and the PER_DIEM-always-pays-per-diem meal calculation.

## Step 8: Finalize PRD — 2026-05-29T13:34:00Z

**Line counts:** PRD.md = 258, PRD_FINALIZED.md = 258. Delta: 0 lines (+0.0%); one existing line revised in place.

**Changes (one bullet per change):**
- §3.3 Funding the Trip — revise — named the error code for the card-issuance over-budget check (`load_limit_cents` exceeding the trip's `remaining_budget_cents` is rejected with `ERR_CARD_LIMIT_EXCEEDED`) — `routes/cards.py:36`.

**Why only one edit.** The Step 7 diff explicitly states all 4 failure clusters were test/fixture bugs and that no implementation changes were made — the server was PRD-faithful throughout. Three of the four clusters touch behavior the PRD already pins verbatim, so they need no PRD edit:
- Receipt-required gate (`>= receipt_required_threshold_cents` → `ERR_RECEIPT_REQUIRED`): already pinned at §3.7 and §3.8. Impl `reports.py:114-120` matches.
- 204-no-body line deletion: already pinned at §4 ("204 No Content"). Impl `lines.py:185` matches.
- PER_DIEM always pays the full GSA per-diem total regardless of meal lines: already pinned at §3.6. Impl `calc.py:98-99` matches.

The fourth cluster (the load≤remaining-budget rule in §3.3) was the one genuine PRD silence: PRD §3.3 stated the rule but never named the error code. The implementation reuses `ERR_CARD_LIMIT_EXCEEDED` (the same code §3.4 uses for a different trigger), which a fresh implementer could not have uniquely derived. Pinned.

**Per-edit pre-edit search log:**
- Edit 1 — §3.3 error code: (a) Subject: error raised when card issuance's `load_limit_cents` exceeds trip's `remaining_budget_cents`. (b) Impl paths: grepped all `ERR_CARD_LIMIT_EXCEEDED` raise sites — exactly two: `routes/cards.py:36` (issuance over-budget, the subject) and `routes/lines.py:134` (line charge exceeds card available_balance, owned by §3.4). Confirmed `errors.py:31` maps code to 409 matching catalogue. (c) Wording adjustment: scoped clause to "an issuance whose `load_limit_cents` exceeds that remaining budget," so it describes only the issuance path and does not overlap the §3.4 line-charge trigger sharing the same code.

## Step 9: Complete PRD — 2026-05-29T13:38:24Z

**Source vs output:** PRD_FINALIZED.md = 258 lines (41601 chars) → PRD_COMPLETED.md = 258 lines (42882 chars); char-delta ~+1289, line count unchanged (all edits in-paragraph).

**Counts:** 8 ambiguity-pins, 1 mismatch-revision. The PRD was already finalized and tightly aligned with implementation/; remaining gaps were response-shape silences (null-vs-absent), unpinned `decision` enum tokens, and one OOP-chain gate mismatch. No new sections/paragraphs.

**Per-change log:**
- §3.2 (trip creation) — insert — ambiguity — pin uninitialized `committed_amount_cents`, `remaining_budget_cents`, not-yet-computed `requires_oop` appear as `null` — `routes/trips.py:71-74`.
- §3.2 (trip decision) — insert — ambiguity — pin `decision` field tokens as exactly `APPROVE`/`DENY` — `routes/trips.py:139`.
- §3.4 (report creation) — insert — ambiguity — pin "not yet finalized" totals and "empty" `return_reason` are `null` (reset to `null` on reopen) — `routes/reports.py:62-64, 227`.
- §3.4 (expense line shape) — insert — ambiguity — pin every line response carries full type-specific field set + omitted `virtual_card_id`, inapplicable fields `null` — `routes/lines.py:107-123`.
- §3.7 (receipt upload) — revise — mismatch — "one receipt per line" parenthetical implied enforced 1:1; revised to state upload does not reject a second receipt — `routes/receipts.py:31-50`.
- §3.7 (receipt OCR fields) — insert — ambiguity — pin "unpopulated" OCR fields present as `null` — `routes/receipts.py:45-46`.
- §3.8 (report decision) — insert — ambiguity — pin `decision` tokens as exactly `APPROVE`/`REJECT`/`RETURN` — `routes/reports.py:137`.
- §3.8 (OOP chain gate on approve) — revise — mismatch — "every approval step must be APPROVED" was vacuously satisfiable with zero steps; revised to require a non-empty chain — `routes/reports.py:163-166`.
- §3.9 (approval-step decision + comment) — insert — ambiguity — pin step `decision` input tokens `APPROVE`/`REJECT` distinct from persisted `APPROVED`/`REJECTED`; pin `comment` as `null` until recorded — `routes/approval_steps.py:36, 73, 86-88`.

One item left unchanged: §3.9's "`step_order` — a one-based position" is descriptive convention; impl validates `step_order` only as a non-negative integer (accepts 0) per §2.6, with no error path rejecting 0, so existing prose contradicts no testable behavior.

---

## Pipeline complete

All 9 steps finished. Final state: **71/71 tests pass across all 8 parallel stability rounds**, deterministic. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (71 tests), workspace/implementation/ (Python+Flask, in-memory, 45 endpoints).
