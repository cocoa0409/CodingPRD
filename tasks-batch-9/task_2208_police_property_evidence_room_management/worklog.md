# Worklog — task_2208_police_property_evidence_room_management

## Step 1: Create task directory — 2026-09-01T01:34:35.601Z

Created `tasks/task_2208_police_property_evidence_room_management/` and `tasks/task_2208_police_property_evidence_room_management/workspace/`.

## Step 2: Generate Scaffold — 2026-09-01T05:07:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files
- `SCAFFOLD.yaml` (§1.0–§1.7 + preamble; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Scaffold size
| Item | Count |
|---|---|
| Entities | 13 (PropertyRoom, OffenseStatute, StorageLocation, Custodian, Case, EvidenceItem, RetentionDetermination, CustodyTransfer, DispositionOrder, OwnerClaim, AuditSession, Discrepancy, ChainEvent — `ChainEvent` immutable, `common_fields: false`) |
| Endpoints | 60 |
| State machines | 10 (EvidenceItem carries two parallel dimensions: `custody_state` and `disposition_state`; Case is cyclic ADJUDICATED↔APPEAL_PENDING) |
| Calculations | 15 |
| Validations | 33 priorities |
| Errors | 61 |
| Roles | 6 (PropertyRoomManager, EvidenceTechnician, Investigator, LabAnalyst, CourtClerk, InternalAuditor) |

Complexity profile: `compliance_audit` / `workflow_orchestration`, topology `flat`, shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; 2 `concurrency_rules` entries.

## Design files
- §1.8: **9 rule_ids / 23 instances** (each rule ≥2 instances) — dual-variant divergence (PRELIMINARY vs FINAL retention; ESTIMATED vs SETTLED auction proceeds), multi-branch derivation, parallel/cyclic state advance, 4-level cascades, priority-pair conflicts, boundary/zero cases, cross-entity gates, interval semantics (half-open custody windows, closed-interval escort capacity, 48h audit buffer), and conserved-quantity round trips (slot ledger, room escrow).
- §1.9: **9 sections / 86 instances** — 61 with full `test_recipe`s, 25 `excluded_because` stubs citing §1.8 instances. Per section: entities 12, state_machines 12, calculations 14, validations 20, endpoints 6, errors 8, rbac 6, cross_cutting_complexity_layers 6, consistency_model 2.

Hardening beyond expert level: weighted check-digit barcode (`CPD-26-00001-0001-2`), tiered auction commission with a recovery cap measured against the post-commission subtotal and per-category storage cost accrual, FINAL retention floored at intake+90d, 4-step ordered nightly sweep whose step order is observable (an item with both a matured retention and an expired owner notice must land in `UNCLAIMED_ELIGIBLE`, not `DISPOSAL_ELIGIBLE`), risk-index rounding per discrepancy before summing, auto-authorization predicate, and 3-way segregation of duties on execution.

One defect found and fixed in `SCAFFOLD.yaml` while building the corner file: `ERR_REFRIGERATION_OUT_OF_RANGE` was untriggerable because `StorageLocation.temperature_c` was constrained to `<= 4.0` at creation, so a warm refrigerated bin could never exist. The recorded reading now accepts `-30.0 .. 30.0`, with the 4.0 C ceiling enforced at assignment time by validation priority 17.

Linter verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2208_police_property_evidence_room_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2208_police_property_evidence_room_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2208_police_property_evidence_room_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     13
  §1.8 instances scanned:     23
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1408

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional independent checks passed: single top-level key in each design file, no `scaffold_*_design` key in `SCAFFOLD.yaml`, all 25 stub citations resolve to real §1.8 instance names (and no stub carries a `test_recipe`), zero duplicate instance names across both design files, all nine §1.9 sections present with no invalid section names, and no forbidden race-condition vocabulary anywhere. The hard constraint was honored — no sibling task directory was inspected.

## Step 3: Copy Shared Files — 2026-09-01T05:08:13.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T05:24:01.000Z

PRD written to `workspace/PRD.md`.

## Deliverable

**443 lines** (444 counting the trailing newline), 20 `###` subsections, ending at §5 with no audit footer. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

## Sections written

- **§1 Introduction** — 3 paragraphs (chain-of-custody framing, the two independent evidence axes, escrow conservation, logical clock).
- **§2 Global Specifications** — 12 domain-derived subsections: 2.1 RBAC, 2.2 API Response Structure (pasted byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Resource Identity/Retrieval/Filtering, 2.5 The Logical Clock, 2.6 Room Posture: The Derived Operating Gate, 2.7 Conservation Invariants, 2.8 Precision/Rounding/Whole-Day Arithmetic, 2.9 Optimistic Concurrency Control, 2.10 Order of Validation (all 33 stages enumerated in order), 2.11 Segregation of Duties and Custodian Eligibility, 2.12 Chain of Custody Documentation.
- **§3 Business Logic & Workflows** — 8 subsections: 3.1 Standing Up a Property Room, 3.2 Intake, 3.3 Getting the Item Into a Bin, 3.4 Retention Determination and the Case Timeline, 3.5 Chain of Custody Transfers, 3.6 Found Property/Owner Notice/Claims, 3.7 Disposition, 3.8 Audits/Discrepancies/Nightly Sweep.
- **§4 Endpoint Definitions** — 4-column table, **60/60** endpoints, preceded by the 201-vs-200 status-code paragraph.
- **§5 Error Code Catalogue** — 2-column table, **61/61** error IDs.

## Coverage audit (machine-verified, two passes)

| Dimension | Scaffold | Covered | Result |
|---|---|---|---|
| Entities | 13 | 13 | PASS |
| Entity field names (verbatim, backticked) | 122 | 122 | 0 missing |
| Endpoint input / query / path identifiers | 72 | 72 | 0 missing |
| Entity enum values (all `constraints` unions) | 91 | 91 | 0 missing |
| State machines | 10 | 10 | PASS |
| State-machine transitions (from/to states named) | 56 | 56 | 0 missing |
| Calculations | 15 | 15 | PASS |
| Validation priorities | 33 | 33 | ordered list in §2.10 |
| Endpoints | 60 | 60 | exact match, no extras |
| Error IDs + HTTP statuses | 61 | 61 | 0 missing |
| Roles | 6 | 6 | each individually named |

**Hard Contract 1 (Field-Name Coverage): PASS** — verified twice; every entity field and every endpoint identifier appears verbatim in backticks. The only scaffold `name:` tokens absent are the 13 internal *calculation labels* (`room_posture`, `barcode_assignment`, `audit_risk_index`, `disposition_proceeds`, etc.), which are not fields or request identifiers; their full content is present in prose.

**Hard Contract 2 (Rule Coverage): PASS** — validation priority ordering stated globally with all three deliberate inversions called out (lockdown above state checks; custody-window conflict below certification; below-reserve above closed-settlement-window) plus the disposition-order carve-out at stage 11; both OCC rules name their write operation, `expected_<parent>_version` field, error ID and 412; all cascades documented (adjudicate → per-item FINAL determinations → conditional DISPOSAL_ELIGIBLE; appeal → COURT_HOLD; reconcile → MISSING discrepancies → occupancy/counter/posture; lockdown → mass transfer denial; execute → item purge + claim release + counters); `applies_to` endpoint sets enumerated for the suspension/certification/restriction/storage-suitability gates; all defaults and initial values stated; sibling-branch symmetry preserved (RETAINED→COURT_HOLD vs DISPOSAL_ELIGIBLE→COURT_HOLD, IN_PROGRESS→CLOSED vs RECONCILED→CLOSED, auto- vs court-authorization, auto-settle vs auction-settle).

**Hard Contract 3 (§3 Path Purity): PASS** — no backtick token in §3 starts with `/`, is a bare HTTP method, or combines method and path; all operations are named by state transition, role + action verb, or capability.

Also verified: no pseudocode or symbolic operators in prose; every threshold stated with its inclusivity; the barcode check-digit worked example (`CPD-26-00001-0001-2`) recomputed by hand and confirmed consistent with the stated algorithm; the pinned rounding order for `risk_index` and the pinned 5-step order for settled proceeds both stated as non-interchangeable; the `ChainEvent` `common_fields: false` exception stated explicitly (only `id` and `created_at`).

## Step 6: Generate Implementation — 2026-09-01T05:56:00.000Z

Implementation complete and verified end to end.

## Files written (`workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` | 13 |
| `requirements.txt` | 1 |
| `app.py` | 78 |
| `store.py` | 129 |
| `errors.py` | 95 |
| `envelope.py` | 95 |
| `validate.py` | 147 |
| `auth.py` | 65 |
| `calc.py` | 228 |
| `serializers.py` | 276 |
| `domain.py` | 451 |
| `routes/__init__.py` | 1 |
| `routes/core.py` | 323 |
| `routes/cases.py` | 432 |
| `routes/custody.py` | 257 |
| `routes/disposition.py` | 430 |
| `routes/audit.py` | 382 |
| **total** | **3403** |

## Endpoints

**60 endpoints implemented — an exact one-to-one match with the 60 declared in `SCAFFOLD.yaml`** (verified by diffing `app.url_map` against the scaffold's `path`/`method` pairs: zero missing, zero extra; Flask's `/static` route excluded). This includes `POST /_clock/set_current_utc` and all 13 resource families.

## Launcher

`start.sh` is executable, `cd`s to its own directory, installs Flask only when the import is missing (guarded so repeated per-test reboots don't contend on pip), and ends with `exec python3 app.py` so the server is the foreground process (no `&`, no subshell). `app.py` reads `int(os.environ.get("PORT", "10000"))` — inherited through the `exec` — and calls `app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)`. Cold boot to first successful `200` measured at **0.62 s**.

## Verification

Two scratch-port smoke suites now pass with **0 failures**:

- Happy path (~120 assertions): clock → room → statute → 4 bins → 7 custodians → case → intake (barcode `CPD-26-00001-0001-2` and check digit `…-0002-9` confirmed) → auto bin selection (fullest-usable-bin ranking) → charge/adjudicate/appeal/resolve-appeal retention cascades (`FINAL` = 30 + ceil(365/2) = 213 days, 90-day floor, `COURT_HOLD` nulling) → transfer request/release (dual signature)/sweep-to-`OVERDUE`/return → report-lost → `LOCKED_DOWN` + escrow/occupancy conservation → discrepancy investigate/resolve → audit schedule (OCC 412, 48 h buffer 409)/start/scan/reconcile (`risk_index` 7.61 from per-discrepancy rounding)/close → auction order authorize/execute/settle (commission 42000, storage recovery 273 × 25 = 6825, net 551175, escrow held then disbursed) → auto-authorized destruction → owner claim file/verify → pagination + envelope shape.
- Error/edge suite (~55 assertions): fresh-boot emptiness on all 11 collections, 33-stage priority order spot-checks (stage 11 before 14, escort capacity before window duration, reserve floor before settlement window, disposition-order carve-out at stage 11 falling through to stages 23/24/25), `ERR_NO_ELIGIBLE_STORAGE` / `ERR_STORAGE_LOCATION_FULL` / `ERR_REFRIGERATION_OUT_OF_RANGE` / `ERR_LOCATION_SEALED` / `ERR_BARCODE_FOREIGN_ROOM` / SoD pairs / `ERR_CLAIM_NOT_VERIFIED` / `ERR_NO_PROCEEDS_HELD` / `ERR_CASE_HAS_UNDISPOSED_ITEMS`, unclaimed-pathway sweep, reject-then-re-request, non-auction execution continuing `EXECUTED → SETTLED` with `settlement_status: NONE`, and gapless per-item chain-of-custody `sequence_no`.

Storage is in-memory dicts only — a `grep` for `sqlite`, `open(`, `json.dump`, `/tmp` and `pickle` across the package returns nothing, and no entity is seeded, preloaded or hardcoded at import time (confirmed by the boot-emptiness assertions). All test servers have been shut down.

## Step 5: Generate Unit Tests — 2026-09-01T06:14:00.000Z

The suite is complete. Final state:

## Files written

**`test_helpers/`** (Stage 1, import-verified): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py` — plus `test_suite/conftest.py`.

**`test_suite/`** — 106 tests, all collected by pytest in 0.62 s, pyflakes clean.

Queue A (depth, 46 tests / 23 instances, >=2 tests each):
| file | tests | rule_id |
|---|---|---|
| `test_01_retention_and_proceeds_variants.py` | 4 | dual_variant_calc (2) |
| `test_02_combinatorial_formulas.py` | 6 | combinatorial_formula (3) |
| `test_03_parallel_and_cyclic_machines.py` | 4 | non_linear_state_machine (2) |
| `test_04_transitive_cascades.py` | 4 | transitive_cascade (2) |
| `test_05_validation_priority_pairs.py` | 6 | priority_pair_validation_conflict (3) |
| `test_06_boundary_precision.py` | 6 | boundary_precision_check (3) |
| `test_07_cross_entity_state.py` | 6 | cross_entity_state_dependency (3) |
| `test_08_temporal_overlap.py` | 6 | resource_temporal_overlap (3) |
| `test_09_compensating_invariants.py` | 4 | compensating_invariant (2) |

Queue B (breadth, 60 tests / 60 instances): `test_20_entities.py` 11, `test_21_state_machines.py` 7, `test_22_calculations.py` 6, `test_23_validations.py` 14, `test_24_endpoints.py` 5, `test_25_errors.py` 6, `test_26_rbac.py` 6, `test_27_cross_cutting.py` 4, `test_28_consistency_model.py` 1.

## Audits (both run centrally over all 18 files)

- **Scaffold-citation pass:** 106/106 tests carry exactly one `Design:` line as the final docstring line; 83 distinct tags; every tag resolves to a real instance with the correct rule_id/section; no class docstring carries a tag; no tag points at an `excluded_because` stub.
- **PRD-citation pass:** all 382 quoted sentences survive a literal (whitespace-normalised) match against `workspace/PRD.md` **and** live in the section number cited — 0 mismatches.
- No occurrence of "scaffold", ".yaml", "design file", "1.x" or queue vocabulary anywhere in generated code.
- The 25 corner stubs delegate to 18 difficulty instance names; all 18 resolve and all are covered by queue A, so no delegated coverage is lost.

## Instances skipped (1)

- `Corner/entities/evidence_item_barcode_computed_field_input_ignored` — the PRD never distinguishes silently ignoring a client-supplied computed field from rejecting it with `ERR_INVALID_REQUEST`, so the asserted outcome is not uniquely derivable. No placeholder emitted.

The 25 corner `excluded_because` stubs were not translated, as required.

## Judgement calls worth flagging to the implementation side

- `audit_reconcile_missing_cascades_to_transfer_denial`: the design's `EvidenceItem.open_transfer_count == 0` after a lockdown denial is not PRD-stated (§2.6 mentions only the escort-capacity decrement), so that one assertion was dropped; the denial + `ROOM_LOCKED_DOWN` + escort release are asserted exactly.
- `unadjudicated_case_disposition_order_rejected`: asserted `AUTHORIZED`/`auto_authorized is True` post-adjudication rather than the design's `PENDING_COURT_AUTH`, because §3.7's auto-authorization predicate holds for that item.
- `derived_field_reconciliation_disposal_eligible_count_after_reject`: `disposal_eligible_count == 0` immediately after order creation is a recomputation reading of §2.4/§3.7 rather than an explicit sentence — the likeliest genuine PRD ambiguity in the suite.

## Step 7: Run Tests and Iterate — 2026-09-01T06:57:00.000Z

All 8 parallel rounds now pass 106/106.

## Summary

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep, 106 tests/round).

- Iteration 1: 102/106 in **all 8** rounds — 4 deterministic failures (no flakiness; the failing set was identical in every round).
- Iteration 2: 106/106 in all 8 rounds.

**Tests deleted:** none. One assertion was removed from a surviving test (STEP 1c partial-coverage split):

- `test_suite/test_21_state_machines.py::TestDisposedItemTerminalStates::test_a_purged_item_admits_no_further_custody_transition` — dropped the `POST /custody-transfers` → `ERR_ITEM_CUSTODY_STATE_INVALID` assertion (plus the dependent "no transfer row written" list check). **STATE-GATE SILENCE:** PRD §3.5 enumerates the transfer-request gates in prose (window sanity, window duration, per-item overlap, escort capacity, custodian active/certified) and names an item-state precondition only for *release* ("the item to be in `STORED`"); §2.10 stages 12/13/19/20/21 explicitly list "requesting a transfer" while stage 11 does not. A faithful implementer can allow the request and gate at release. Scaffold rule that drove it: `Corner/state_machines/disposed_item_cannot_start_new_transfer`. The PRD-derivable half (`POST /evidence-items/{itemId}/storage-assignment` on a `PURGED` item → `ERR_ITEM_CUSTODY_STATE_INVALID`, from §3.3 "advances an item's custody dimension from `LOGGED` to `STORED`") was kept.

**Fixes applied to `test_helpers/`:** none — all four failures were test-function bugs or PRD ambiguity, not fixture/factory/header bugs.

**Fixes applied to `test_suite/`:**

- `test_09_compensating_invariants.py::TestEscrowBalanceIsRestoredOnDisbursement::test_disbursement_returns_the_balance_to_zero_and_cannot_repeat` — relaxed the second-disburse assertion from exact `ERR_NO_PROCEEDS_HELD` to `validate_error_is_one_of([ERR_NO_PROCEEDS_HELD, ERR_ORDER_STATE_INVALID])` (HTTP 409 still asserted). **ERROR PRECEDENCE SILENCE:** §3.7 names `ERR_NO_PROCEEDS_HELD` for disbursement without held proceeds, while §2.10 stage 11 puts the order's own state check (`ERR_ORDER_STATE_INVALID`) ahead of stage 31; an already-`DISBURSED` order trips both, and PRD does not say which wins.
- `test_21_state_machines.py::TestAuditSessionLifecycle::test_start_seals_the_bin_and_snapshots_only_its_stored_items` — location `version` expectation corrected from `+1` to `+2`. The test read the bin *before* scheduling, and PRD §3.8 increments the location's `version` twice: "Creating it also increments the target location's `version` by 1" and, on start, "has its `version` incremented by 1". Test bug.
- `test_26_rbac.py::TestSegregationOfDutiesAtExecution::test_executor_may_not_be_the_requester_nor_the_witness` — two assertions changed from `status == "EXECUTED"` to `status == "SETTLED"`. Both orders are `DESTRUCTION`, and PRD §3.7 states a `RETURN_TO_OWNER`/`DESTRUCTION`/`CONVERSION` order "continues `EXECUTED → SETTLED` inside the same request". Test bug.
- Removed the now-unused `custody_transfer_payload` / `validate_error` imports left by the above edits (pyflakes clean).

**Fixes applied to `workspace/implementation/`:** none. Every failure traced to the test layer or to non-uniquely-derivable PRD prose; no implementation check was weakened, no endpoint/field/side effect was added, and storage remains in-memory dicts only.

## Step 8: Finalize PRD — 2026-09-01T07:04:00.000Z

Done. `PRD_FINALIZED.md` written with two surgical edits.

## Line counts
- `PRD.md`: 443 lines; `PRD_FINALIZED.md`: 443 lines (0.00% line delta — both edits are in-paragraph insertions/revisions on existing long lines; +9 sentences-worth of prose, ~+0.8% by character count).

## Changes
- **§3.5 (Chain of Custody Transfers, para 1)** — insert — states that `POST /custody-transfers` performs no check against the item's `custody_state` or `disposition_state`, that the custody-state precondition belongs to release (`STORED`), and that a request against a `LOGGED` / `CHECKED_OUT` / `MISSING` / `PURGED`+`DISPOSED` item is not refused on item-state grounds — `implementation/routes/custody.py:49-100` (gate list ends at line 78; no item-state branch anywhere in the handler).
- **§3.7 (Disposition, final para)** — revise — pins disbursement precedence: order status must be `SETTLED` first (`ERR_ORDER_STATE_INVALID`, explicitly covering a repeat disbursement of an already-`DISBURSED` order), then `settlement_status` must be `HELD` (`ERR_NO_PROCEEDS_HELD`) — `implementation/routes/disposition.py:317-320`.

Two `<step_7_diff>` items required **no** PRD change (both pure test bugs, PRD already uniquely determines them): audit-session-start location `version` `+2` (§3.8 already states both increments, at create and at start — `routes/audit.py`), and `EXECUTED → SETTLED` for `DESTRUCTION` orders (§3.7 already states the same-request continuation — `disposition.py:258-262`).

## Per-edit pre-edit search log

**Edit 1 — §3.5 transfer-request item-state gate**
- (a) Subject: whether/where an evidence item's `custody_state` and `disposition_state` gate custody-transfer operations, and what `POST /custody-transfers` actually validates.
- (b) Enumerated & read: `routes/custody.py` in full — `request_transfer` (lines 49–100: 404 resolution of item + to_custodian, `gate_locked_down`, `gate_restricted`, `gate_active`, `gate_certified`, escort capacity, window sanity, window duration, `_window_conflict`, then row creation), `release_transfer` (142–147: transfer `REQUESTED`, item `STORED`, location `OPEN`), `return_transfer` (195–200: item `CHECKED_OUT`), `report_lost` (241–244: item `CHECKED_OUT`); helpers `_escort_load` / `_window_conflict` (only look at transfer `status`, never at item state); `domain.py` `OPEN_TRANSFER_STATUSES`, `gate_active`, `gate_certified`, `refresh_item_transfer_count`, `refresh_custodian`, `refresh_room` (the `LOCKED_DOWN` → `DENIED` cascade, which also never reads item state); parallel item-state gates elsewhere for contrast: `routes/disposition.py:64` (`ORDER_PENDING`/`DISPOSED`), `:218` (`custody_state != STORED` at execution), `routes/core.py`/`audit.py` storage-assignment path referenced by §3.3.
- (c) Adjustment: initial draft said the request "produces a `REQUESTED` row like any other" and that release gates "those dimensions". Both were false universals — a `CHECKED_OUT` item with an overlapping window still trips `ERR_CUSTODY_WINDOW_CONFLICT` (`custody.py:77`), and release checks only `custody_state`, never `disposition_state` (no impl path gates `disposition_state` on any transfer op). Rewrote to the check-level claim ("makes no check against"), scoped release's precondition to `custody_state` alone, and softened the outcome clause to "is not refused on item-state grounds", which leaves the window/escort/certification refusals intact. Deliberately said nothing about `ERR_LOCATION_SEALED` at request time (also unchecked there) to avoid widening beyond the Step 7 subject while not implying it is checked.

**Edit 2 — §3.7 disbursement precondition precedence**
- (a) Subject: the ordered preconditions of `POST /disposition-orders/{orderId}/disburse` and which of `ERR_ORDER_STATE_INVALID` / `ERR_NO_PROCEEDS_HELD` wins.
- (b) Enumerated & read: `routes/disposition.py` `disburse_order` (306–328: role, 404, `payee_reference`, `gate_locked_down`, then `status != "SETTLED"` → `ERR_ORDER_STATE_INVALID`, then `settlement_status != "HELD"` → `ERR_NO_PROCEEDS_HELD`); every other producer/consumer of `status` and `settlement_status` on an order, to enumerate which states can reach each branch — `create_order` (92/102: `PENDING_COURT_AUTH`, `NONE`), `authorize_order` (162), `reject_order` (183–186: `REJECTED`), `execute_order` (216–217, 231, 258–262: `EXECUTED`, then non-auction → `SETTLED` + `settlement_status` `NONE`), `settle_order` (281–299: `EXECUTED` → `SETTLED` + `HELD`); `domain.refresh_room` (267–269) confirming only `HELD` orders contribute to `escrow_balance_cents`, so the `DISBURSED` short-circuit leaves escrow untouched; §2.10 stages 11 and 31 for stated priority; `test_suite/test_25_errors.py:265-330` as auxiliary confirmation that the surviving exact-`ERR_NO_PROCEEDS_HELD` case is the non-auction `SETTLED`+`NONE` order.
- (c) Adjustment: an earlier draft made `ERR_ORDER_STATE_INVALID` the blanket answer for "no proceeds held", which would have contradicted the immediately preceding §3.7 sentence (kept verbatim) that a non-auction `SETTLED` order with `settlement_status` `NONE` is refused with `ERR_NO_PROCEEDS_HELD` — the one live path to that error. Re-scoped to a two-condition, explicitly ordered statement so both the `SETTLED`+`NONE` path and every non-`SETTLED` status (`PENDING_COURT_AUTH`, `AUTHORIZED`, `REJECTED`, `EXECUTED`, `DISBURSED`) are described correctly, and left §2.10 stages 11/31 untouched since they already encode this precedence.

## Step 9: Complete PRD — 2026-09-01T07:16:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Stats

- `PRD_FINALIZED.md`: 443 lines / 82,697 chars → `PRD_COMPLETED.md`: 445 lines / 93,199 chars (**+2 lines, +10,502 chars**)
- 37 existing lines revised in place; 1 new paragraph inside the existing §5 (no new sections, no new headings — heading count unchanged at 28)
- **Ambiguity-pins: 30 · Mismatch-revisions: 7**

## Changes

- §2.1 RBAC — insert — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty for `ERR_MISSING_USER_CONTEXT` — `implementation/auth.py:44`
- §2.2 Success envelope — insert — ambiguity — `total_count` is the pre-window filtered count; `has_more` is `offset + rows_returned < total_count` — `implementation/envelope.py:53`
- §2.3 Pagination — insert — ambiguity — empty-string `limit`/`offset` treated as omitted; non-integer, out-of-band `limit` or negative `offset` → `ERR_INVALID_REQUEST` (400) — `implementation/envelope.py:72-88`
- §2.3 Pagination — insert — ambiguity — equal `created_at` ties break on server creation sequence, everywhere the PRD says "ascending `created_at`" — `implementation/store.py:126-129`
- §2.4 Resource identity — **revise** — mismatch — `version` bumps at most once per row per request, rows created by the request stay at 1, and a no-op recomputation bumps neither `version` nor `updated_at` — `implementation/store.py:84-103`, `implementation/domain.py:121-125`
- §2.4 Filtering — insert — ambiguity — empty/unknown query params ignored; exact string equality; `superseded` accepts `true/1/false/0` case-insensitively and anything else matches nothing — `implementation/validate.py:129-147`
- §2.6 Room posture — insert — ambiguity — all five room counters are re-derived from underlying rows on every recomputation, not tallied incrementally — `implementation/domain.py:237-289`
- §2.8 Precision — insert — ambiguity — `risk_index`/`weight_contribution` serialize as JSON numbers, so `0.00` renders `0.0` — `implementation/serializers.py:8-13,242,256`
- §2.10 stage 11 — insert — ambiguity — fixed within-stage order (path resource → item → location) with the per-endpoint error sequence spelled out — `implementation/routes/custody.py:142-147`, `implementation/routes/disposition.py:216-219`, `implementation/routes/audit.py:116-119,311-314`
- §2.10 stage 17 — **revise** — mismatch — `ERR_REFRIGERATION_OUT_OF_RANGE` arises only on storage assignment; discrepancy resolution never re-checks bin temperature — `implementation/routes/audit.py:316-320`
- §3.1 Offense statutes — insert — ambiguity — `description` required as a string, otherwise unconstrained — `implementation/routes/core.py:131`
- §3.1 Storage locations — insert — ambiguity — `temperature_c` shape/band failures and non-null readings on other categories are `ERR_INVALID_REQUEST` at stage 6 — `implementation/routes/core.py:184-190`
- §3.1 Custodians — insert — ambiguity — `full_name` must be non-empty — `implementation/routes/core.py:261`
- §3.1 Suspension — insert — ambiguity — `reason` non-empty; re-suspending a non-`ACTIVE` custodian → `ERR_CUSTODIAN_SUSPENDED` — `implementation/routes/core.py:316-319`
- §3.2 Intake — **revise** — mismatch — the intake determination is the one exception to the `RETENTION_SET` rule, so intake writes exactly one chain entry (`INTAKE`, `sequence_no` 1) — `implementation/routes/cases.py:257-267`
- §3.3 Storage assignment — insert — ambiguity — non-`LOGGED` item → `ERR_ITEM_CUSTODY_STATE_INVALID`; `storage_location_id` may be omitted or explicitly null — `implementation/routes/cases.py:302,311-312`
- §3.3 Auto-select — insert — ambiguity — final tie-break after `created_at` is location creation order — `implementation/routes/cases.py:365-372`
- §3.4 FINAL variant — **revise** — mismatch — the `ADJUDICATED` requirement is only enforced when neither override branch applies; otherwise a `FINAL` request succeeds and resolves to `COURT_HOLD`/`INDEFINITE` — `implementation/routes/cases.py:397-403`
- §3.4 Appeals — insert — ambiguity — every cascade requests `basis` `FINAL`, so the stored `basis` reads `FINAL` while `resolved_basis` may read `COURT_HOLD`/`INDEFINITE` — `implementation/routes/cases.py:132,157,182`
- §2.12 Chain of custody — insert — ambiguity — `sequence_no` is re-derived across the item's whole chain on every append, with write order as final tie-break, so a clock rewind renumbers later entries — `implementation/domain.py:327-333`
- §3.5 Transfer request — insert — ambiguity — `open_escort_count` and `open_transfer_count` are re-derived from the open-transfer set, not tallied — `implementation/domain.py:148-172`
- §3.5 Release — **revise** — mismatch — an empty-string `witness_signature` counts as omitted; `released_signature` must be non-empty — `implementation/routes/custody.py:131,152-154`
- §3.5 Return — insert — ambiguity — `receipt_signature` must be non-empty — `implementation/routes/custody.py:186`
- §3.5 Report-lost — insert — ambiguity — requires non-`LOCKED_DOWN` room, transfer in `RELEASED`/`OVERDUE`, item `CHECKED_OUT` (`ERR_ITEM_CUSTODY_STATE_INVALID`), and makes no custodian eligibility check; the raised discrepancy's `weight_contribution` stays 0.00 forever — `implementation/routes/custody.py:233-252`, `implementation/domain.py:436`
- §3.6 Owner notice — insert — ambiguity — notice issuance makes no item-state check and an item may carry several claims; `claimant_name`/`claimant_contact` non-empty — `implementation/routes/disposition.py:340-346`
- §3.6 Filing/verification — insert — ambiguity — late or wrong-status filing → `ERR_CLAIM_STATE_INVALID`; verification takes no body — `implementation/routes/disposition.py:402-428`
- §3.6 Sweep expiry — insert — ambiguity — the item moves only from `RETAINED`; other states expire the claim and leave the item alone; no chain entry — `implementation/routes/core.py:101-108`
- §3.7 Retention maturity gate — **revise** — mismatch — `COURT_HOLD` also yields `ERR_RETENTION_NOT_MATURED`, not just `RETAINED` — `implementation/routes/disposition.py:81-82`
- §3.7 Authorization/refusal — insert — ambiguity — auto-authorization writes no chain entry; `court_order_number` and `reason` must be non-empty and the refusal `reason` is persisted nowhere — `implementation/routes/disposition.py:117-120,157,177`
- §3.7 Settlement — **revise** — mismatch — wrong `type` and wrong `status` both report `ERR_ORDER_STATE_INVALID`; `gross_sale_cents` integer ≥ 0 — `implementation/routes/disposition.py:275,281-282`
- §3.7 Disbursement — insert — ambiguity — `payee_reference` must be non-empty — `implementation/routes/disposition.py:311`
- §3.8 Scheduling — insert — ambiguity — `auditor_id` resolves to a `Custodian` and must be `ACTIVE`, but no certification check applies — `implementation/routes/audit.py:40,46`
- §3.8 Scanning — insert — ambiguity — no membership test; repeat scans append/count/document again and re-raise; null `storage_location_id` counts as misplaced; `risk_index` stays 0.00 until `reconciled_at` is set — `implementation/routes/audit.py:165-195`, `implementation/domain.py:195-219`
- §3.8 Resolution — insert — ambiguity — `resolution_note` non-empty; a `MISSING` discrepancy requires the item to still be `MISSING` (`ERR_ITEM_CUSTODY_STATE_INVALID`), checked right after the discrepancy status — `implementation/routes/audit.py:300,313-314`
- §3.8 Resolution (MISSING/FOUND) — insert — ambiguity — an item holding no bin has no capacity check and simply returns to `STORED` — `implementation/routes/audit.py:326-328`
- §3.8 Session close — **revise** — mismatch — the seal is released only when `sealed_by_audit_session_id` still names this session; posture is recomputed either way — `implementation/routes/audit.py:247-252`
- §3.8 Sweep step four — insert — ambiguity — location `occupied_slots` are re-derived first; every step is room-scoped; the sweep writes no chain entries — `implementation/routes/core.py:90-118`
- §4 Endpoint definitions — insert — ambiguity — which resource each mutating call returns (storage assignment → item, sweep → room, scan/reconcile → session, report-lost → transfer); the clock returns only `current_utc`/`previous_utc` — `implementation/routes/cases.py:342`, `implementation/routes/core.py:42,119`, `implementation/routes/audit.py:197,227`, `implementation/routes/custody.py:257`
- §5 Error catalogue — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` (404), bad method → `ERR_METHOD_NOT_ALLOWED` (405), non-object body → `ERR_INVALID_REQUEST` — `implementation/app.py:46-62`, `implementation/validate.py:20`

Notable judgment calls: I treated the PRD's incremental "increments/decrements the counter" phrasing as description rather than mechanism (impl re-derives everywhere), and pinned §2.10 stage 17 down to category-only for discrepancy resolution since the implementation never re-checks refrigerated temperature there.

## Step 9b: Final confirmation sweep — 2026-09-01T07:26:00.000Z

Regenerated the `results.{1..8}.json` artifacts (a subagent had cleaned them up after Step 7). Re-ran the full 8-round parallel `per-test-server` sweep against the post-Step-8/9 tree: **106/106 in all 8 rounds** (Step 8 and Step 9 touched only PRD documents, never `implementation/` or the tests).
