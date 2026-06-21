# Worklog — task_0378_land_surveying_services

Scenario: Land Surveying Services: order & survey type (boundary/topo/ALTA/elevation), parcel/deed research, field-crew scheduling & equipment, fieldwork & data, plat/drawing production & seal, revision, rush, deliverable & invoice
Difficulty: Expert

## Step 1: Create task directory — 2026-06-16T00:00:00.000Z

Created `tasks/task_0378_land_surveying_services/` and `tasks/task_0378_land_surveying_services/workspace/` (pre-assigned index; no scan/auto-increment).

## Step 2: Generate scaffold (Expert) — 2026-06-16T00:00:00.000Z

All three scaffold artifacts are complete, internally consistent, and pass the linter cleanly.

Generated three scaffold artifacts for **task_0378_land_surveying_services** at the **Expert** difficulty band:
- `SCAFFOLD.yaml` (§1.0–§1.7, plus `complexity_profile` and `concurrency_rules`) — 1564 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 1734 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 1428 lines

**Structural counts:**
- Entities: 11 — CrewMember, Instrument, SurveyOrder, ResearchPacket, FieldAssignment, InstrumentReservation, DataSet, PlatDrawing, RevisionRequest, Deliverable, Invoice
- State machines: 5 (SurveyOrder branching+revert, ResearchPacket cyclic title-hold loop, FieldAssignment, PlatDrawing seal/revision cycle, Invoice with parallel lifecycle × payment axes) + 2 concurrency rules (OCC on order version for seal and invoice-issue)
- Calculations: 5 — order_fee_estimate (tiered per-acre), invoice_final_fee (actual variant + tax/reseal), revision_reseal_fee, assignment_window_minutes, crew_member_risk_score
- Validations: 19 (priority-ordered, auth → existence → state → OCC → business safety/referential/temporal/constraint)
- Endpoints: 53
- Errors: 19
- Roles: 6 — Coordinator, Researcher, FieldTech, Drafter, Surveyor, BillingClerk (segregation-of-duties, all entity_backed to CrewMember)

**Design instances:**
- §1.8 difficulty-design: 18 instances (all 9 Difficulty Rules × 2)
- §1.9 corner-design: 29 instances (23 active + 6 `excluded_because` stubs)

**Key Expert mechanics:** dual-variant fee accounting (estimate 144000 vs final 199180 after CLIENT_CHANGE reseal+tax), tiered-rate acre pricing with round-after-sum order, depth-3 cancel cascade (order→assignment→reservation→instrument), two distinct interval semantics (half-open crew adjacency vs buffered instrument turnaround), OCC on SurveyOrder.version, SEALED→DRAFTING revision-revert loop. `scaffold_lint.py` returns `VERDICT: clean lint`. `api_prefix` set to `""` (flat topology).

## Step 3: Copy shared files — 2026-06-16T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-16T00:00:00.000Z

Generated `workspace/PRD.md` (272 lines) from SCAFFOLD.yaml only; did not open either withheld design file.

**Section structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Hierarchical Consistency & state propagation, 2.6 Monetary Precision, 2.7 Asset/License/Calibration integrity, 2.8 OCC, 2.9 Validation Ordering); §3 Business Logic (3.1 intake pipeline, 3.2 deed research, 3.3 field scheduling/reservations/data capture, 3.4 cancellation release cascade, 3.5 plat drafting/sealing/revision loop, 3.6 deliverables/invoicing/settlement, 3.7 fee/window calculations, 3.8 crew risk score); §4 Endpoint Definitions (54-endpoint table); §5 Error Code Catalogue (19 errors).

**Coverage:** all 11 entities (60/60 field names), all 6 state machines, 4 calculations + risk-score, all 19 validations (priority-ordered), all 54 endpoints, all 19 errors, all 6 roles. Hard Contracts 1 (Field-Name Coverage 60/60), 2 (Rule Coverage), 3 (§3 Path Purity) all PASS.

## Step 5: Generate unit tests — 2026-06-16T00:00:00.000Z

NOTE: the Step 5 subagent's final summary message was lost to a socket-close error after it had completed all 52 tool uses and written every file to disk. The following is reconstructed from on-disk verification (all artifacts confirmed present, syntactically valid, and Design-tagged):

- `test_helpers/`: __init__.py, api_client.py, api_errors.py, assertions.py, constants.py, factories.py, fixtures.py, test_users.py, types.py (9 files, all parse OK).
- `test_suite/`: conftest.py + 6 test files — test_01_fee_calculations.py (9), test_02_state_machines.py (9), test_03_cascades_and_invariants.py (8), test_04_seal_and_boundaries.py (12), test_05_validations_and_rbac.py (10), test_06_entities_crud.py (7).
- Total: **55 tests**, every one carrying exactly one `Design:` tag (no untagged, no dual-tagged). Queue split: 32 queue A (Difficulty/) + 23 queue B (Corner/) = 55.
- All 16 test/helper files pass `ast.parse`.

## Step 6: Generate implementation — 2026-06-16T00:00:00.000Z

Generated a complete Python + Flask implementation at `workspace/implementation/`.

**File list:** start.sh (executable, foreground, guarded pip install), requirements.txt (Flask 3.0.3), app.py (entry/error-handlers/routes; reads $PORT, binds 0.0.0.0), db.py (in-memory Store, one dict per entity), errors.py (ApiError + 20-entry catalog), response.py (meta/response_type/data envelope + pagination), middleware.py (X-User-ID/X-User-Role auth, six roles, RBAC), calculations.py (fee/window/risk via Decimal + ROUND_HALF_UP), helpers.py (field/enum/type validation, existence, pagination, computed counts), serializers.py (output shaping w/ refreshed computed fields), routes.py (50+ endpoints across 11 entities).

**Framework/storage:** Flask + strictly in-memory dicts (Store), instantiated once at module load, never seeded — empty on every boot, wiped on each start.sh re-invocation (nothing persisted to disk).

**Structure:** Response envelope (meta{api_request_id, api_request_timestamp, +pagination}, response_type object/array/error, data); ISO-8601 UTC timestamps with 3 fractional digits; bare-UUID ids; created_at/updated_at/version common fields (version starts 1, bumps on every mutation incl. cascade/propagation). State machines: SurveyOrder pipeline + cancel; ResearchPacket TITLE_HOLD re-open cycle; FieldAssignment; PlatDrawing DRAFTED→UNDER_REVIEW→SEALED + IN_REVISION loop; Invoice parallel lifecycle/payment axes. Bubble-up propagations each independently bump order version. Calculations: tiered acreage field fee (5@8000/next15@5000/rest@3000, band products rounded half-up), 30% rush, 8.25% tax, reseal-fee-by-reason lookup, floor window minutes, weighted risk score — all Decimal/ROUND_HALF_UP integer cents. Validations ordered per PRD §2.9: auth(401)→role(403)→existence(404 L-to-R)→body(400)→state(409)→OCC(412)→business. OCC expected_order_version on plat-seal and invoice-issue only. Cascades: order-cancel depth-3 release (assignment→reservation→instrument), each bumped.

**start.sh confirmation:** reads $PORT (app.py default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`, pip install guarded behind `import flask` check.

## Step 7: Run tests and iterate — 2026-06-16T14:56:04.000Z

- **Iterations run.** 1 full 8-round concurrent sweep after the diagnosis/fixes (all 8 rounds 55/55, zero failures/errors, ~35.7s each, no "could not be restarted" setup failures). The orchestrator's pre-existing single-process probe was 52/55; my fixes resolved the 3 logic failures and the concurrency-contention root cause.

- **Tests deleted.** None. (No PRD-silent tests found; the two non-uniquely-derivable error_id assertions were relaxed, not deleted — see below.)

- **Fixes applied to `test_helpers/`.** None. The fixtures driving all three previously-failing tests (`order_at_in_progress_packet`, `draft_invoice_on_sealed_order`) were verified PRD-faithful — they correctly build the gated-precondition scenarios under test.

- **Fixes applied to `test_suite/`** (these are the test-layer fixes, not test_helpers):
  - `test_01_fee_calculations.py` — `test_invoice_rounding_order_round_after_sum`: corrected the asserted `total_cents` from `583999` to `584009` (and the matching docstring). The test's own subtotal (539500) + tax (44509) = 584009; `583999` was an arithmetic typo in the test, contradicting PRD §3.7 "The invoice `total_cents` is `subtotal_cents` plus `tax_cents`." The implementation's value was PRD-correct (STEP 2 test bug — assertion mistranslation).
  - `test_04_seal_and_boundaries.py` — `test_clear_research_blocked_while_packet_in_progress` and `test_deliverable_release_blocked_without_issued_invoice`: relaxed each exact `validate_error(..., ERR_INVALID_STATE)` to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_VALIDATION])`. Both cited PRD sentences (§3.2 research_clear gate, §3.6 cross-entity delivery gate) name no error_id, and §2.9 does not uniquely classify a flag-gate / cross-entity referential check as "state-machine legality" vs a domain business rule (which §5 catalogs as the generic `ERR_VALIDATION`). The error_id is not uniquely PRD-derivable, so per the cardinal-rule relaxation exception the assertion was widened to the two faithful readings; all exact side-effect assertions (status unchanged, entity unchanged) were preserved.

- **Fixes applied to `implementation/`.**
  - `app.py` (module-import time, before `create_app`): stubbed `socket.getfqdn` to return `"localhost"`. Root cause of the concurrent-sweep contention: Werkzeug's `make_server` with `host="0.0.0.0"` calls `socket.getfqdn()` to compute a cosmetic `server_name`, and reverse-resolving this machine's `.local` hostname blocked ~5s per boot. Across 8 concurrent rounds × 55 per-test reboots that blew past the restart window (the prior 0/55 sweeps). The stub drops boot-to-200 from 5.3s to 0.2s; binding still targets `0.0.0.0` per the evaluator contract — only the unused name resolution changed. No PRD behavior, endpoints, fields, or seeding were added; storage remains in-memory dicts wiped on every boot.

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-16T14:59:56.000Z

Produced `workspace/PRD_FINALIZED.md` — a minimal patch of `PRD.md` targeting the `<step_7_diff>` items.

**PRD.md vs PRD_FINALIZED.md:** line count 272 → 272 (0% line delta; both edits inline within existing lines). Word count 6270 → 6339 (+69 words, +1.1%). Char count 43059 → 43615 (+556 chars, +1.3%).

**Changes (one bullet each):**
- §3.2 — insert — pinned that the `clear-research` `research_clear`-flag gate (order in `RESEARCH` but `research_clear` still false) returns `ERR_VALIDATION`, distinguishing it from the order's own `RESEARCH`-status legality check which returns `ERR_INVALID_STATE` — `implementation/routes.py:219` (contrast `:217`).
- §3.6 — insert — pinned that each of the two cross-entity delivery conditions (released deliverable must reference a `SEALED` plat; order must already have an `ISSUED` invoice) returns `ERR_VALIDATION` when unmet, distinguishing them from the deliverable's `ASSEMBLED`-status and the order's `SEALED`-status legality checks which return `ERR_INVALID_STATE` — `implementation/routes.py:863` and `:871` (contrast `:858` and `:865`).

**Step 7 items requiring NO PRD edit:** the `app.py socket.getfqdn` stub is a pure boot-performance change with no PRD-observable behavior; the `total_cents` test typo (583999→584009) confirmed impl matches PRD §3.7 verbatim (subtotal → tax half-up → total), a pure test typo. Both needed no PRD change.

**Per-edit NO-NEW-MISMATCH search log:**
- Edit 1 (§3.2 research_clear gate): subject = error_id of the `clear-research` flag gate vs order-status legality check. Grepped all `ERR_VALIDATION`/`ERR_INVALID_STATE` in `routes.py`; read `clear_research` (`:212-222`); cross-checked neighboring `ERR_VALIDATION` sites (`:206` start-research packet-count, `:323` begin parent-order-RESEARCH, `:355` hold encumbrance) — none describe the research_clear flag. Wording scoped narrowly to "this `research_clear`-flag gate" + carved out the `RESEARCH`-status check as `ERR_INVALID_STATE`.
- Edit 2 (§3.6 delivery gate): subject = error_id for each of the two cross-entity release conditions vs deliverable/order status legality checks. Read `release_deliverable` (`:853-877`: `:858` ASSEMBLED→`ERR_INVALID_STATE`, `:863` plat-not-SEALED→`ERR_VALIDATION`, `:865` order-not-SEALED→`ERR_INVALID_STATE`, `:871` no ISSUED/CLOSED invoice→`ERR_VALIDATION`) and `create_deliverable` (`:824-825` assembly plat-SEALED→`ERR_VALIDATION`, consistent). Wording limited to "these two cross-entity conditions" + explicitly named the `ASSEMBLED`/`SEALED` status requirements as `ERR_INVALID_STATE`, avoiding a false-universal claim about the order-status SEALED gate at `:865`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-16T15:09:28.000Z

Produced `workspace/PRD_COMPLETED.md` — a full PRD-vs-`implementation/` scan starting from `PRD_FINALIZED.md`.

NOTE: the Step 9 subagent's final summary message was lost to an `API Error: socket connection closed unexpectedly` after it had completed 28 tool uses and written every edit to disk (same failure mode as Step 5). The following is reconstructed from on-disk verification — `PRD_COMPLETED.md` confirmed structurally complete (272 lines, identical §1–§5 section structure and §5 tail to PRD_FINALIZED.md, all 8 edits clean inline insertions/revisions, no truncation):

**Source (PRD_FINALIZED.md) vs PRD_COMPLETED.md:** line count 272 → 272 (inline edits only); char count 43615 → 45365 (+1750 chars, +4.0%).

**Counts:** ambiguity-pins: 6 lines (pure); mismatch-revisions: 2 lines (both in §3.5, each also carrying an ambiguity-pin). 8 edited lines total.

**Changes (one bullet each):**
- §2.3 (Pagination) — insert — ambiguity — a present-but-non-integer `limit`/`offset` is rejected with `ERR_INVALID_REQUEST`; a parseable out-of-range value is silently clamped (`limit`<1→1, `limit`>100→100, negative `offset`→0) rather than rejected — `implementation/helpers.py` pagination parsing.
- §2.3 (Ordering) — insert — ambiguity — list endpoints sorted by `created_at` ascending break ties by `id` ascending — `implementation/serializers.py`/listing helper sort key.
- §3.1 (Order Intake) — insert — ambiguity — INTAKE→RESEARCH packet-count precondition (exactly one ResearchPacket), when unmet, returns `ERR_VALIDATION`; the order's own `INTAKE`-status legality check returns `ERR_INVALID_STATE` — `implementation/routes.py` begin-research.
- §3.2 (Deed Research) — insert — ambiguity — placing a hold is permitted only when `encumbrance_count` ≥ 1; holding at zero is rejected with `ERR_VALIDATION` — `implementation/routes.py` packet-hold.
- §3.3 (Field Scheduling) — insert — ambiguity — assignment start: parent order not in `FIELD_READY`/`IN_FIELD`, or crew member inactive → `ERR_VALIDATION`; the assignment's own `SCHEDULED`-status legality check → `ERR_INVALID_STATE` — `implementation/routes.py` start-assignment.
- §3.5 (Plat Drafting) — insert+revise — ambiguity + mismatch — revised "at least one of the order's datasets is `ACCEPTED`" → "the named source dataset is `ACCEPTED`" (mismatch with impl, which checks the named dataset), and pinned plat-creation error_ids: order not `DATA_READY` → `ERR_INVALID_STATE`, named source dataset not `ACCEPTED` → `ERR_VALIDATION`; submit-for-review with non-`ACCEPTED` source dataset → `ERR_VALIDATION` — `implementation/routes.py` create-plat / submit-plat.
- §3.5 (Sealing) — insert+revise — ambiguity + mismatch — pinned the domain-rule evaluation order after state-legality + OCC as segregation-of-duties → licensure → closure-tolerance (reordered prose from licensure-first to match impl), and added that a missing license also yields `ERR_SEAL_NOT_LICENSED` — `implementation/routes.py` seal-plat.
- §3.5 (Revision Loop) — insert — ambiguity — applying a revision requires the targeted plat to be in `SEALED` or `UNDER_REVIEW`; applying against any other plat state is rejected with `ERR_INVALID_STATE` — `implementation/routes.py` apply-revision.
