# Worklog — task_1142_damage_prevention_underground_damage_claim

## Step 1: Create task directory — 2026-08-11T00:49:00.000Z

Task directory `tasks/task_1142_damage_prevention_underground_damage_claim/` and its `workspace/` subdirectory pre-created (index pre-assigned as 1142; auto-index scan skipped per instruction). Recorded by orchestrator.

## Step 2: Generate scaffold — 2026-08-11T01:27:00.000Z

Scaffold generation complete for task 1142. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1142_damage_prevention_underground_damage_claim/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

**Design summary** (calibrated above Expert band per the difficulty parameter — density-first, compliance/audit primary archetype + multi-party negotiation secondary):

- **Entities: 17** — Excavator, Locator, LocateTicket, LocateResponse, DamageCase (parallel status dimensions: investigation × recovery), EvidenceItem + TimelineEvent (append-only, `common_fields: false`), FaultAllocation (self-referential supersede chain), CostLineItem, ClaimInvoice (dual-basis amounts), Payment, Dispute (polymorphic target), SubrogationCase, RegulatoryReport (self-referential amend chain), ViolationRecord, TrainingCourse, TrainingAssignment
- **State machines: 13** — including parallel dimensions (DamageCase), two cyclic negotiation loops (FaultAllocation contest/revise, Dispute respond/counter), threshold-band machine with training-gated downgrade (Excavator)
- **Calculations: 11** — incl. dual variants (rule-default vs adjudicated fault shares; actual vs standard cost basis), pinned nested rounding (per-line then allocate, remainder absorbed by largest share), decay+banding offender score, deadline penalties, two waterfall allocations, chronological timeline reconstruction, deterministic training-course selector
- **Validations: 12** (ordered priorities; auth → ownership → existence → state → SoD safety → temporal → referential → constraint → fiscal → OCC → close gate)
- **Endpoints: 74** — flat topology under `/damage-recovery`, incl. `POST /_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` startup default and expiry sweeps
- **Errors: 29**; **Roles: 7** (IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager — opaque; Excavator/Locator — `entity_backed:` with ownership checks; System), role model `segregation_of_duties` (finalize caller ≠ investigator_user_id); **concurrency rules: 1** (OCC on DamageCase.version for create-with-supersede, `ERR_STALE_VERSION` 412)

**§1.8 difficulty instances: 18** (9 rules × 2, each with a differentiating clause honored: different entity domains, modes (a) vs (b), different cascade triggers at depth 3/2, different error-category pairs, different metrics/endpoints, different entity pairs, half-open vs closed interval semantics, money vs allocation-mass conserved quantities).

**§1.9 corner instances: 53** (47 active + 6 `excluded_because:` stubs), spanning all nine claim-guide sections (entities 8, state_machines 6, calculations 7, validations 10, endpoints 1, errors 12, rbac 4, cross-cutting 4, consistency 1).

**Coverage-audit notes:**
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (576 calls scanned, 74 endpoints, 17 entities, 18 + 47 instances).
- Placeholder closure verified programmatically: zero unbound `${var}`; instance names unique across the §1.8∪§1.9 union; all 6 stub targets resolve to real §1.8 instance names.
- All 29 error codes are referenced by §1.2/§1.4/§1.5 AND exercised by at least one §1.8/§1.9 instance.
- Every formula-derived assert literal was executed and verified (e.g., 120000/131250 basis split, 84000 vs 60000 divergent shares, 414000 vs 500000 cap interaction, 2304 rounding-order trap vs naive 2305, 5500000 cap breach, 10-day penalty 10000, waterfall 120000/30000, subrogation 50000+20000+30000 conservation).
- Fixes applied during self-audit: removed dead enum `TICKET_RENEWED` (renewals are field-reflected, not event-sourced), added missing `Locator` suspend endpoint + state machine (ERR_LOCATOR_INACTIVE was otherwise untriggerable), added the `FAULT_PROPOSED → INVESTIGATING` revert so the contest→revise→re-propose cycle is reachable, reworded one "simultaneously" in a stub rationale; forbidden-vocabulary scan is clean.
- Setup-chain replay was performed per instance (call-by-call preconditions + forward side-effect replay, e.g. case version bumps before OCC captures, clock positions before sweeps/deadlines).

## Step 3: Copy shared files — 2026-08-11T01:29:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1142_damage_prevention_underground_damage_claim/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T01:36:00.000Z

**PRD generated**: `/home/ubuntu/github/CodingPRD/tasks/task_1142_damage_prevention_underground_damage_claim/workspace/PRD.md`

**Line count**: 323 lines

**Section list**:
- §1 Introduction
- §2 Global Specifications & System-Wide Principles (12 subsections: 2.1 RBAC, 2.2 API Response Structure [verbatim block], 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock, 2.6 Hierarchical Consistency & Cascades, 2.7 Nested Resource Retrieval, 2.8 Precision & Rounding, 2.9 OCC, 2.10 Segregation of Duties, 2.11 Repeat-Offender Bands, 2.12 Logical-Clock Sweeps)
- §3 Business Logic & Workflows (9 subsections organized by business process: registration → ticket/response → intake/evidence → investigation/fault-allocation → costs/invoicing → payments/reversals → offender program/training → disputes/subrogation → regulatory filings/case closure)
- §4 Endpoint Definitions (74 endpoints in 4-column table)
- §5 Error Code Catalogue (29 errors in 2-column table)

**Entity coverage**: 15 / 15 entities covered (Excavator, Locator, LocateTicket, LocateResponse, DamageCase, EvidenceItem, TimelineEvent, FaultAllocation, CostLineItem, ClaimInvoice, Payment, Dispute, SubrogationCase, RegulatoryReport, ViolationRecord, TrainingCourse, TrainingAssignment — note: that is 17 entries in the scaffold; all 17 covered).

**Hard-contract audit results**:

- **Contract 1 (Field-Name Coverage)**: required=114, present=114, missing=0 — PASS (after two repair passes that added `to_iso8601`, `verdict`, `points`, `effective_points`, `response_note`, `counter_note` in narrative-appropriate locations).
- **Contract 2 (Rule Coverage)**: all 29 error IDs present in prose; all state-machine states and transitions expressed (including the parallel `investigation_status` × `recovery_status` dimensions, cyclic `PROPOSED → CONTESTED → DRAFT` fault-allocation negotiation, and `RECOVERED → COLLECTING` reversal cascade); all 11 calculations expressed in business prose with no pseudocode (rounding pinned per-line, basis-point share table fully enumerated, decay buckets 365/1095 days, late-filing 30-day window with 5000 + 500/day capped at 100000 cents, waterfall orderings stated); the single OCC rule (`expected_damage_case_version` on fault-allocation create → `ERR_STALE_VERSION` / 412) is expressed without time-overlap framing; segregation-of-duties rule expressed; sibling branches (rule-default vs adjudicated shares, actual vs standard cost basis, five `root_cause_code` mappings) given equal prose density. PASS.
- **Contract 3 (§3 Path Purity)**: 647 backtick tokens scanned inside §3, 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS. Endpoints are referenced in §3 exclusively via state-pair framing (e.g., "moving `investigation_status` to `FAULT_PROPOSED`"), role + action verb ("a `RecoveryManager` finalizes"), or capability description ("an admin-only test-driving capability sets the clock").

## Step 5: Generate unit tests — 2026-08-11T02:05:00.000Z

Generation complete. All 80 tests collect cleanly under pytest with `PYTHONPATH=<task_dir>`.

## File inventory

**test_helpers/** (9 files, 55,245 bytes):
- `__init__.py` (1,026) — barrel export: framework generics + PRD-specific
- `types.py` (9,947) — 17 entity TypedDicts + 19 status/role enums; `EvidenceItem`/`TimelineEvent` correctly omit `updated_at`/`version` (PRD §2.4)
- `api_client.py` (12,061) — `ApiClient(GenericApiClient)` with 61 methods, one per PRD §4 endpoint
- `api_errors.py` (3,338) — 29 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (8,019) — per-entity `assert_*`, `parse_iso`, `assert_case_invoice_conservation`
- `factories.py` (4,708) — 14 payload factories, input fields only
- `constants.py` (1,905) — markups, standard rates, caps, thresholds, temporal windows
- `test_users.py` (2,612) — `TEST_USERS` + per-role `make_*_headers` builders (entity-backed Excavator/Locator threaded by real id)
- `fixtures.py` (16,629) — composite tiers: single creators, `begin_investigation`/`create_allocation`/`propose`/`finalize`, `setup_case_investigating` → `setup_proposed_allocation` → `setup_finalized_case` → `setup_issued_invoice_case` → `setup_paid_case` / `setup_disputed_invoice`

**test_suite/** (10 files, 109,799 bytes): `conftest.py` + `test_01` registration/envelope/intake (9 tests), `test_02` tickets/responses (7), `test_03` case/evidence/timeline (8), `test_04` fault-allocation cycle (13), `test_05` costs/invoicing (9), `test_06` payments/write-offs/reversals (11), `test_07` disputes/subrogation (8), `test_08` offender program/training (7), `test_09` regulatory/closure (8).

## Test counts per design source
- **Queue A (Difficulty): 34 tests** covering 17 of 18 instances at exactly 2 tests each.
- **Queue B (Corner): 46 tests** covering 46 of 47 non-stub instances at 1 test each. All 6 `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` cross-reference resolves.

## Skipped instances (2, with reasons)
1. **Difficulty/priority_pair_validation_conflict/finalize_sod_beats_invoice_authority_cap** — PRD §3.4 lists finalize's three preconditions as an unordered semicolon list; unlike contest ("the state check is evaluated before the temporal check"), no verbatim sentence pins SoD-before-cap ordering, so unique derivability fails (validation-priority silence pattern). Consequence: two corner stubs pointing at it (`priority_conflict_safety_beats_fiscal_stub`, `segregation_of_duties_pattern_stub`) also remain uncovered; plain SoD rejection is untestable without freelance discovery, which is forbidden.
2. **Corner/calculations/locator_performance_score_after_audits** — PRD states only the initial `performance_score_bp` 10000 (§3.1) and that it is "recomputed on every audit" (§2.6); the aggregation formula (floor(10000 × ACCURATE/audited) → asserted 5000) appears nowhere in PRD prose, so the expected value is not uniquely derivable.

## Self-audit verdicts
- **Coverage audit**: expected shortfalls are exactly the 2 skipped instances above; every translated instance meets its target (≥2 queue A, ≥1 queue B); no unknown tags, no tags pointing at stubs, no untagged or dual-tagged tests, every `Design:` line is the docstring's final line.
- **PRD-citation pass**: 93 quoted citation segments across 80 tests, all verified verbatim against PRD.md via whitespace-normalized substring grep — 0 failures (3 initially non-verbatim elided quotes were rewritten to full sentences and re-verified).
- **Scaffold-citation pass**: all 80 tags resolve to real instance names in the source yamls.
- **Hygiene**: no `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold"/table references in generated code; all asserted `error_id`s are named in PRD prose (not just the §5 table); 80/80 tests collected by pytest.

## Step 6: Generate implementation — 2026-08-11T02:05:00.000Z

Implementation complete. All smoke checks pass.

## Summary

Generated a complete Python + Flask implementation of the Damage Prevention & Underground Damage Claim Recovery API at `/home/ubuntu/github/CodingPRD/tasks/task_1142_damage_prevention_underground_damage_claim/workspace/implementation/`.

### File inventory (source files, sizes)

| File | Bytes | Purpose |
|---|---|---|
| `start.sh` | 321 | Foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op once flask present), reads `$PORT` (default 10000) |
| `requirements.txt` | 16 | `flask>=3.0,<4.0` |
| `app.py` | 2168 | App factory, blueprint registration, ApiError/404/405/exception handlers |
| `db.py` | 1236 | In-memory store (dicts per entity, sequence counters); **no seeding** |
| `clock.py` | 408 | Logical clock, startup default `2026-05-01T00:00:00Z` |
| `errors.py` | 4819 | ApiError + all 28 scaffold error IDs with exact HTTP statuses |
| `middleware.py` | 803 | `X-User-ID`/`X-User-Role` validation against the 6 declared roles |
| `util.py` | 5120 | Envelope (`meta`/`response_type`/`data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, cap 100), datetime/enum/int validation, `req_` IDs, 3-fractional-digit timestamps |
| `serializers.py` | 7729 | Entity serializers; EvidenceItem/TimelineEvent correctly omit `updated_at`/`version` |
| `services/core.py` | 11854 | All 11 calculations (per-line rounding w/ Decimal ROUND_HALF_UP, allocation remainder absorption, standard vs actual basis, offender decay, filing penalty, payment waterfall, timeline reconstruction, subrogation split, locator score, training selector), cascades, expiry sweep |
| `routes/` (13 files) | ~76 KB | One module per resource group |

### Endpoint count
All **61 endpoints** from the PRD §4 endpoint table are implemented: 1 clock, 4 excavator, 3 locator, 4 ticket, 4 response, 7 damage-case, 3 evidence, 2 timeline-event, 6 fault-allocation, 4 cost-line, 4 claim-invoice, 4 payment, 6 dispute, 4 subrogation, 5 regulatory-report, 4 violation, 3 training-course, 4 training-assignment (list counts include GETs).

### Verification performed
- Two custom end-to-end smoke suites (approx. 130 assertions) run against fresh boots — all pass: auth/RBAC errors, ticket overlap/adjacency/renew, response audit + locator score, evidence 72h admissibility, timeline reconstruction flags (NO_TICKET/LATE_MARK/STALE_MARKS/POST_DAMAGE_MARK), OCC 412, supersede, propose/contest/revise cycle, segregation-of-duties 403, finalize cascade (invoices conserve to subtotal, dual standard/actual basis, auto ViolationRecord + band upgrade + auto TrainingAssignment), payment waterfall + credit balance + reversal clawback, dispute negotiation + escalation → subrogation → settlement split (apply+legal+owner == recovered), write-off caps, late-filing penalty, program-band gating on incomplete training, expiry sweeps, pagination meta.
- Fresh-process boot: store empty (no seeding), clock default verified, binds `0.0.0.0:$PORT`, serves HTTP within ~2s of `bash start.sh`.

### Notable design decisions
- **Write-off precondition ordering**: a DISPUTED invoice with an open dispute yields `ERR_INVOICE_HAS_OPEN_DISPUTE` (not `ERR_INVALID_STATE`) — otherwise that error would be unreachable since open disputes always set DISPUTED.
- **Duplicate dispute on an already-DISPUTED invoice** yields `ERR_INVALID_STATE` per the scaffold's validation priority (state, priority 5, beats business_constraint, priority 9).
- Envelope `api_request_timestamp` uses wall-clock per PRD §2.2 wording; all business-logic timestamps (`created_at`, deadlines, sweeps) use the logical clock exclusively.
- Offender points recompute on excavator reads and clock sweeps so decay buckets stay current.

## Step 7: Run tests and iterate — 2026-08-11T02:20:00.000Z

## Summary

- **Iterations run**: 3 sweep iterations (iteration 1: 4 real bugs identified and fixed; iteration 2: confirmed fixes worked, surfaced 8-way-parallel server-boot flakes; iteration 3: clean).

- **Tests deleted**: None. All 4 original failures traced to PRD-verbatim rules and were either test bugs or implementation bugs.

- **Fixes applied to `test_helpers/`**: None.

- **Fixes applied to `test_suite/`**:
  - `test_04_fault_allocation_cycle.py` — `TestReviseConservation._setup_contested(self)` referenced `api.contest_fault_allocation(...)` without taking the `api` fixture. Added `api` parameter and updated both call sites (`test_revise_cycle_conserves_allocation_mass`, `test_revise_with_mis_summed_shares_rejected`) to pass it through. Pure test bug — NameError from a missing fixture parameter.

- **Fixes applied to `implementation/`**:
  - `workspace/implementation/routes/claim_invoices.py` (`write_off_invoice`) — After setting `inv["status"] = "WRITTEN_OFF"`, added `inv["amount_due_cents"] = 0`. PRD §3.5 verbatim: "A successful write-off moves the invoice to `WRITTEN_OFF`, forgives the remaining `amount_due_cents`...". Previously the field kept its pre-write-off value (15000), violating the forgiveness clause.
  - `workspace/implementation/routes/disputes.py` (`create_dispute`) — Reordered guard clauses so `ERR_DISPUTE_ALREADY_OPEN` fires before the `ERR_INVALID_STATE` check on the target's status. PRD §3.8 lists the duplicate-dispute rule before the state rule, and a `DISPUTED` invoice (which is the state produced by an existing OPEN dispute) must hit ALREADY_OPEN, not INVALID_STATE.

- **Final 8-round sweep result**: 80/80 passed in all 8 rounds (passed=80, failed=0, errors=0 across the board).

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` files present on disk, each `passed=80 total=80 failed=0`. Route-parity pre-check (orchestrator, pre-sweep): all 74 SCAFFOLD.yaml (method, path) endpoint pairs registered in implementation, none missing, none extra.

## Step 8: Finalize PRD — 2026-08-11T02:26:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1142_damage_prevention_underground_damage_claim/workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 323 lines, PRD_FINALIZED.md = 323 lines — 0% line-count delta; 3 of 323 lines modified inline (~0.9% of lines touched, character-level delta only).

**Changes (one bullet each):**
- §3.5 — revise — write-off sentence now states the concrete field effect: "forgives the remaining `amount_due_cents` — the invoice's `amount_due_cents` is set to 0 —" — `workspace/implementation/routes/claim_invoices.py:90-93` (Step 7 fix that added `inv["amount_due_cents"] = 0` in `write_off_invoice`).
- §2.6 — revise — derived-total definition of `ClaimInvoice.amount_due_cents` gains the carve-out "; a successful write-off then sets it to 0 (§3.5)" so the universal `invoiced − paid` formula no longer contradicts the WRITTEN_OFF state — same impl site, `claim_invoices.py:93` (required to keep the document internally consistent with the §3.5 edit).
- §3.8 — insert — explicit guard precedence in dispute creation: the duplicate-dispute (`ERR_DISPUTE_ALREADY_OPEN`) check is evaluated before the target-status (`ERR_INVALID_STATE`) check, with the DISPUTED-invoice case named — `workspace/implementation/routes/disputes.py:52-61` (Step 7 fix that reordered the guards in `create_dispute`).

**Step 7 items needing no PRD edit:** the `test_04_fault_allocation_cycle.py` `_setup_contested` fixture fix is a pure test bug (missing `api` fixture parameter) — no PRD silence or mismatch.

**Per-edit pre-edit search log:**

1. **§3.5 write-off edit**
   - (a) Subject: value of `ClaimInvoice.amount_due_cents` after a successful write-off.
   - (b) Enumerated: `routes/claim_invoices.py:75-100` (write-off: state guard, open-dispute guard, cap check at line 88 reading the pre-zero value, then zeroing at line 93); `services/core.py:93-94` (`recompute_invoice_amount_due` formula, still used by payments `payments.py:67,82`, reversal `payments.py:164`, dispute resolution `disputes.py:153`, escalation `disputes.py:205`, expiry sweep `core.py:319`); `services/core.py:97-110` (debtor outstanding sums only ISSUED/PARTIALLY_PAID/DISPUTED — WRITTEN_OFF excluded regardless); `services/core.py:284-295` (terminal-state case advance); `routes/subrogation.py:71` (settlement reads `amount_due_cents`); `serializers.py:155` (field exposed); `routes/fault_allocations.py:299` (creation init); test evidence `test_06:174-178` asserts `amount_due_cents == 0` post-write-off.
   - (c) Wording scoped to the write-off act ("is set to 0" as the operation's effect), not a lifetime invariant — because `payments.py:63-71` (explicit-invoice payment, no status guard) can later recompute the field on a WRITTEN_OFF invoice. No claim made about which invoice states are write-off-eligible (impl also accepts DISPUTED at `claim_invoices.py:80`; that pre-existing divergence is outside the Step 7 scope and was deliberately left untouched).

2. **§2.6 derived-total carve-out**
   - (a) Subject: the general definition of `amount_due_cents`.
   - (b) Same enumeration as edit 1, plus verification that every other writer of the field (`core.py:94`, `payments.py`, `disputes.py:153,205`, `core.py:319`, `fault_allocations.py:299`) uses the `invoiced − paid` formula, and write-off is the sole override.
   - (c) Chose act-scoped phrasing ("a successful write-off then sets it to 0") over a state-based universal ("a WRITTEN_OFF invoice has `amount_due_cents` 0"), which would be falsified by the explicit-payment-on-WRITTEN_OFF path noted above.

3. **§3.8 guard-precedence edit**
   - (a) Subject: evaluation order of the duplicate-dispute check vs. the target-status check when opening a dispute.
   - (b) Enumerated: `routes/disputes.py:41-61` — both target branches (CLAIM_INVOICE lines 52-56, FAULT_ALLOCATION lines 57-61) check already-open first; target resolution/`ERR_DISPUTE_TARGET_MISMATCH` precedes both (PRD already lists it first — consistent); `services/core.py:335-348` (`has_open_dispute`, `has_open_dispute_on_allocation` — state sets match PRD verbatim); grep confirmed `err_dispute_open` is raised only at `disputes.py:54,59`, so no other endpoint is affected; the write-off endpoint's opposite ordering (state check at `claim_invoices.py:80` before open-dispute check at line 82) involves a different error (`ERR_INVOICE_HAS_OPEN_DISPUTE`) and a different operation, so it is not mis-described by dispute-creation-scoped wording; style precedent exists in §3.4's contest rule ("the state check is evaluated before the temporal check").
   - (c) Wording scoped to dispute creation only; covers both target kinds by referencing "the target-status check that follows" (the very next sentence covers both ClaimInvoice and FaultAllocation); the DISPUTED-invoice example matches the impl comment and the `test_07` duplicate-dispute test (`setup_disputed_invoice` → ALREADY_OPEN).

## Step 9: Complete PRD — 2026-08-11T02:42:00.000Z

All edits applied and verified. The diff touches 30 lines on the completed side (28 revised in place, 2 inserted), no new sections, no removed sections.

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1142_damage_prevention_underground_damage_claim/workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md = 323 lines / 54,425 chars → PRD_COMPLETED.md = 325 lines / 59,937 chars (**+2 lines, +5,512 chars**).

**Counts:** 27 ambiguity-pins, 4 mismatch-revisions (31 inline edits total; all in-paragraph, no new sections).

### Ambiguity pins (27)
- §2.2 — insert — generic request-validation failures (missing field, bad enum, malformed datetime, wrong/non-positive scalar) → `ERR_INVALID_REQUEST` 400; undefined path or unsupported method → `ERR_NOT_FOUND` 404 — `implementation/util.py:55-67,144-179`; `implementation/app.py:41-47`
- §2.3 — insert — `limit` > 100 is clamped, not rejected; `created_at` ties break by insertion order; enumerated every list endpoint's equality-filter query params (incl. payments `claim_invoice_id` matching allocation legs) — `implementation/util.py:103-141`; list handlers in `implementation/routes/*.py`
- §2.4 — revise — `TCK-<seq>` / `DC-<seq>` counters start at 1, increment by 1 — `implementation/db.py:32-38`
- §2.5 — insert — clock-set response `data` carries `current_utc` — `implementation/routes/clock_routes.py:20`
- §2.12 — insert — dispute-expiry cascade: target invoice leaves `DISPUTED` (status recomputed from paid, case recovery + debtor outstanding recomputed); sweep also refreshes all excavators' `offender_points` — `implementation/services/core.py:300-332`
- §3.1 — revise — suspending a non-`ACTIVE` locator → `ERR_INVALID_STATE` — `implementation/routes/locators.py:61-62`
- §3.2 — insert — `performance_score_bp` formula: 10000 if no audited responses, else floor(10000·ACCURATE/audited) — `implementation/services/core.py:113-124`
- §3.2 — insert — renew requires caller's `X-User-ID` == ticket's `excavator_id` — `implementation/routes/locate_tickets.py:110-111`
- §3.2 — insert — submitting a response against a `COMPLETED` ticket is permitted; only the first response flips `OPEN`→`COMPLETED` — `implementation/routes/locate_responses.py:60-64`
- §3.3 — revise — intake's optional `locate_ticket_id` is resolved for existence only; no status/window check at intake — `implementation/routes/damage_cases.py:38-42`
- §3.4 — revise — one flag per event with precedence `POST_DAMAGE_MARK` > `LATE_MARK` > `STALE_MARKS`; `reconstruction_flags` written in fixed order `NO_TICKET, LATE_MARK, STALE_MARKS, POST_DAMAGE_MARK`; response `data` = `{created_event_count, reconstruction_flags}` — `implementation/routes/damage_cases.py:169-226`
- §3.4 — revise — allocation create: `INVESTIGATING` state check evaluated before the OCC version check — `implementation/routes/fault_allocations.py:102-107`
- §3.4 — revise — `contest_note` accepted but not persisted or returned — `implementation/routes/fault_allocations.py:193-212`
- §3.4 — revise — supplying `shares` on revise re-records `basis` as `ADJUDICATED` — `implementation/routes/fault_allocations.py:227-231`
- §3.4 — revise — finalize's three preconditions evaluated in the order listed — `implementation/routes/fault_allocations.py:259-265`
- §3.5 — revise — `quantity` may be any positive number, not necessarily an integer — `implementation/routes/cost_lines.py:30`; `implementation/util.py:169-173`
- §3.5 — revise — write-off also bumps the parent case's `version` — `implementation/routes/claim_invoices.py:96-99`
- §3.6 — revise — reversing a non-`APPLIED` payment → `ERR_INVALID_STATE` — `implementation/routes/payments.py:155-156`
- §3.7 — revise — offender score is also recomputed whenever an `Excavator` is read — `implementation/routes/excavators.py:51,63-64`
- §3.7 — revise — overturning a non-`ACTIVE` violation → `ERR_INVALID_STATE` — `implementation/routes/violations_training.py:95-96`
- §3.7 — revise — complete: `ASSIGNED` state check evaluated before the ownership check — `implementation/routes/violations_training.py:208-211`
- §3.8 — insert — no ownership check against the target at dispute open; any `Excavator`/`Locator` may file — `implementation/routes/disputes.py:26-86`
- §3.8 — revise — `response_note` / `counter_note` accepted but not persisted or returned — `implementation/routes/disputes.py:117-145`; `implementation/serializers.py:176-189`
- §3.8 — insert — escalating an allocation-target dispute: `claim_invoice_id` null, `demand_amount_cents` 0, target party = `EXCAVATOR` share else first share, `FACILITY_OWNER` recorded as `EXCAVATOR` — `implementation/routes/disputes.py:207-215`
- §3.8 — revise — settlement requires `DEMANDED`; both amounts non-negative; settlement pulls a `DISPUTED` invoice out of `DISPUTED` and moves the case `INVOICED`→`COLLECTING` on positive application; close from any other status → `ERR_INVALID_STATE` — `implementation/routes/subrogation.py:58-83,101-102`
- §3.9 — insert — `period_end` before `period_start` → `ERR_INVALID_REQUEST` — `implementation/routes/regulatory_reports.py:45-46`
- §3.9 — revise — amend copies `payload_notes` unless the call supplies a new one — `implementation/routes/regulatory_reports.py:152-155`
- §4 — insert — report-amend responds HTTP 200 carrying the new `DRAFT` successor — `implementation/routes/regulatory_reports.py:179`

### Mismatch revisions (4)
- §3.5 — revise — write-off is allowed from `ISSUED`, `PARTIALLY_PAID`, **or `DISPUTED`** (PRD said only the first two); a `DISPUTED` invoice's status is recomputed from `amount_paid_cents` before the cap check — `implementation/routes/claim_invoices.py:80-89`
- §3.6 — revise — reversal: a `DISPUTED` invoice reduces `amount_paid_cents` but **remains `DISPUTED`** until its disputes resolve; a `RECOVERED` case returns to `COLLECTING` whenever any reversed leg targeted one of its invoices (not only when a terminal invoice reopens) — `implementation/routes/payments.py:163-180`
- §2.6 — revise — `ClaimInvoice.amount_paid_cents` definition extended to include subrogation-settlement applications — `implementation/routes/subrogation.py:72`
- §2.6 — revise — cascade summary clause reworded: reversal with a leg on any of a recovered case's invoices flips `RECOVERED`→`COLLECTING` — `implementation/routes/payments.py:176-180`

Everything else in the implementation (endpoint/role matrix, state machines, markup/multiplier/cap arithmetic, allocation waterfall with residual absorption, decay thresholds, filing-penalty formula, OCC scope, segregation-of-duties, error catalog) matched the PRD as written and was left untouched.
