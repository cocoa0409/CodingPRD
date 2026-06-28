# Worklog — task_0663_holiday_event_decor_install

## Step 1: Task directory — bash-only

Directory `tasks/task_0663_holiday_event_decor_install/` and `workspace/` pre-existing. Per execution directives, Step 1 directory-scan SKIPPED; folder used verbatim as {task_dir}. Difficulty: Expert (propagated only to Step 2).

## Step 2: Generate scaffold — 2026-06-26

All three scaffold artifacts generated (Expert difficulty). scaffold_lint.py returns VERDICT: clean lint across all 530 setup/trigger calls and FK reverse-reachability checks.

Complexity profile: temporal_windowing (primary) + pricing_engine (secondary); hybrid topology; parallel state-machine shape; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions.

Counts:
- Entities: 13 — Client, Contract, DesignProposal, ProposalLineItem, InventoryItem, Crew, WorkOrder, Visit, StorageLot, StorageBay, DamageReport, RestockOrder, RenewalOffer.
- State machines: 8 — Contract (cyclic renewal loop), DesignProposal, WorkOrder (schedule dim), WorkOrderBilling (2nd parallel dim on same row), DamageReport (REPAIR/RESTOCK fork-join), StorageLot, RenewalOffer (branch accept/decline/expire), RestockOrder. Plus 2 concurrency rules (OCC on Contract.version).
- Calculations: 7 — compute_install_fee (tiered bundle, round-per-line), compute_storage_fee (threshold), compute_contract_total (nonlinear early-bird, mode a), compute_route_minutes (round-per-leg then sum, mode b), compute_damage_settlement (order-pinned circular dep + loyalty waiver, mode c), compute_renewal_price (provisional vs final dual-variant), compute_crew_utilization (planned vs actual dual-variant).
- Validations: 16 (priority-ordered). Endpoints: 65 (incl. POST /_clock/set_current_utc, default 2026-04-01T00:00:00Z). Errors: 18. Roles: 4 — AccountManager, FieldSupervisor, ClientContact (entity_backed:Client), PlatformAdmin.
- §1.8 instances: 19 total (≥2 per all 9 difficulty rules; combinatorial_formula carries 3 for modes a/b/c). §1.9 instances: 39 total = 32 active corner tests + 7 excluded_because stubs.

api_prefix = "" (resources at root-level paths like /contracts, /work-orders).

Files: SCAFFOLD.yaml (1732 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1481 lines), SCAFFOLD_CORNER_DESIGN.yaml (1381 lines).

## Step 3: Copy INSTRUCTION.md — bash-only

cp ./INSTRUCTION.md workspace/INSTRUCTION.md

## Step 4: Generate PRD — 2026-06-26

Generated workspace/PRD.md (~291 lines, 46348 bytes). 5 top-level sections, 10 §2 subsections, 9 §3 workflow subsections, §4 endpoint table (4 cols), §5 error table (2 cols).

Hard Contract reports all PASS:
- Contract 1 (field coverage): 59/59 entity fields, 4/4 request bodies, 10/10 query params. PASS.
- Contract 2 (rule coverage): 16/16 validations, 2/2 OCC rejections, all state-machine transitions, 7/7 calculations, 18/18 validation conditions, all side-effects/cascades, sibling-branch symmetry. PASS.
- Contract 3 (path purity §3): 431 backtick tokens scanned, 0 path/method tokens. PASS.

§2.2 emitted byte-for-byte from template. Confirmed: SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

## Step 5: Generate unit tests — 2026-06-26

test_helpers/ (9 files): types.py (14 entity TypedDicts + 12 enums), api_client.py (~60 endpoint methods incl clock), api_errors.py (18 errors + HTTP map), assertions.py (per-entity for 14 entities), factories.py, constants.py, test_users.py (opaque roles + make_client_contact_headers for entity-backed ClientContact), fixtures.py (setup_active_contract, create_completed_takedown, setup_sent_renewal_offer, create_stored_lot, etc.), __init__.py.

test_suite/ (conftest + 5 files, 70 test functions):
- test_01_pricing_calculations.py — difficulty rules 1, 2, 6
- test_02_state_machines_and_cascades.py — difficulty rules 3, 4
- test_03_constraints_and_invariants.py — difficulty rules 5, 7, 8, 9
- test_04_corner_crud_and_validation.py — corner entities/validations/endpoints/errors/RBAC
- test_05_corner_workflows_and_calculations.py — corner state-machines/calculations/cross-cutting/consistency

Coverage: Queue A all 19 instances × 2 = 38 tests; Queue B all 32 non-stub instances × 1 = 32 tests. Total 70 tests, 70 Design: tags (1 each, exact match). 7 excluded_because corner stubs correctly NOT translated. None weakened/skipped. Rule-5 priority-pairs framed as single-applicable-failure isolated scenarios citing PRD §2.6 state-machine-guard sentence. All 70 collect under pytest; pyflakes clean; no skip/xfail.

## Step 6: Generate implementation — 2026-06-26

implementation/ (21 files): start.sh (reads $PORT default 10000, binds 0.0.0.0, foreground exec python3 app.py, guarded pip install), requirements.txt (Flask 3.0.3), app.py, db.py (in-memory dicts + logical clock + base-field helpers), errors.py (19 error IDs), response.py (meta/response_type/data envelope, req_ IDs, ISO8601 ms), middleware.py (X-User-ID/X-User-Role + RBAC), validation.py (parse/type/enum/numeric/pagination limit 10 range 1-100 offset 0/ISO/clock), services/calculations.py (7 calcs, Decimal ROUND_HALF_UP), routes/*.py (12 files).

Endpoints: 65 implemented, matches PRD table 1:1. Storage in-memory only (no SQLite/JSON/open). No seeding. Clock default 2026-04-01T00:00:00Z. Smoke-tested pricing, routing, utilization, double-booking, bay capacity, damage settlement, RESTOCK fork, fulfill replenish, depth-3 renewal cascade, OCC 412, validation precedence.

## Step 7: Run tests and iterate — 2026-06-26T19:37:51.000Z

All 8 parallel rounds pass (67/67 each, stable across every round). Iteration complete.

Summary

- **Iterations run:** 2 sweeps (1 baseline + 1 after fixes). Baseline: 62/70 in all 8 rounds with a stable union of 8 failing tests. Final: 67/67 in all 8 rounds, empty failure union.

- **Tests deleted (3) — PRD-silence/unique-derivability category:**
  - `test_storage_fee_flat_at_exactly_20_stored_units` (test_01) — UNREACHABLE-PRECONDITION / unique-derivability collapse. PRD §3.6 requires the owning contract to be SIGNED or ACTIVE before a lot can be checked-in (STORED); PRD §3.3 computes the storage fee at the one-time PROPOSED→SIGNED transition over STORED lots. No lot can be STORED at sign time, so a faithful implementation always yields flat 15000 and the "sign with 20 STORED units" scenario cannot be constructed. (Scaffold driver: Difficulty/boundary_precision_check/storage_fee_threshold_at_20_units_on_signed_lots.)
  - `test_storage_fee_overage_just_above_20` (test_01) — same UNREACHABLE-PRECONDITION collapse; additionally asserts 15600, an outcome PRD makes impossible at sign time. (Same scaffold driver.)
  - `test_storage_fee_overage_above_twenty_units` (test_05) — same UNREACHABLE-PRECONDITION collapse, asserting 15600. (Scaffold driver: Corner/calculations/storage_fee_overage_above_twenty_units.)

- **Fixes applied to `test_suite/` (test layer):**
  - `test_03_constraints_and_invariants.py` — `TestStorageBayCapacityConservedOnRelease._bay_with_released_30`: the fixture checked a lot in under a DRAFT contract, violating PRD §3.6's SIGNED/ACTIVE precondition (the 5-shared-setup-error cluster). Rebuilt it to use `setup_active_contract` so check-in/release run against an ACTIVE contract. Fixes `test_released_lot_frees_full_capacity` and `test_released_lot_status_is_released`.
  - `test_04_corner_crud_and_validation.py` — `test_stale_contract_version_on_proposal_accept`: fixture passed `accepted_a["version"] - 1` (a *proposal* version that coincidentally equalled the current *contract* version), so OCC passed and the superseded loser tripped ERR_INVALID_STATE. Changed to carry `proposed["version"]` (the genuinely now-outdated contract version per §2.7) so OCC fires ERR_STALE_CONTRACT_VERSION.
  - `test_04_corner_crud_and_validation.py` — `test_proposal_accept_when_sibling_already_accepted_returns_already_decided`: fixture passed a proposal version as `expected_contract_version` (OCC fired stale). Now re-fetches the contract's current version so the request reaches the decision layer, and relaxed the assertion to `validate_error_is_one_of(["ERR_PROPOSAL_ALREADY_DECIDED", "ERR_INVALID_STATE"])` per the ERROR-PRECEDENCE collapse rule (§2.6 state-guard priority 8 precedes the business rule; the supersede cascade makes the loser SUPERSEDED, so it legitimately surfaces ERR_INVALID_STATE). Added `validate_error_is_one_of` to the import block.

- **Fixes applied to `implementation/`:**
  - `routes/work_orders.py` — `_crew_double_booked`: changed the buffer comparison from strict `< BUFFER` to `<= BUFFER`. PRD §3.4 specifies a closed-interval, buffer-strict check where "a date falling within one day of an existing window is a collision," so a date exactly one day from an existing window must be rejected with ERR_CREW_DOUBLE_BOOKED. Fixes `test_schedule_within_one_day_buffer_rejected` while leaving `test_schedule_well_clear_of_buffer_succeeds` passing.

## Step 8: Finalize PRD — 2026-06-26T19:40:52.000Z

Step 8 ran (Step 7 had 3 deletions + 3 test_suite fixes + 1 implementation fix → not skipped). Produced workspace/PRD_FINALIZED.md.

The patch is complete. One edit applied.

Line counts: PRD.md = 291 lines, PRD_FINALIZED.md = 291 lines. Net delta: 0 lines (+0.0%); one line revised in place (§3.4).

Per-change bullet:
- §3.4 (Crew double-booking) — revise — Resolved the exact-one-day boundary ambiguity: changed "must clear ... by at least a one-day buffer ... a date falling within one day ... is a collision" to "must clear ... by more than a one-day buffer ... a date whose absolute gap from an existing window is one day or less is a collision; the one-day boundary itself is inclusive, meaning a date falling exactly one day before or after an existing window is a collision." — routes/work_orders.py:105 (abs(requested_dt - existing_dt) <= BUFFER).

Why only one edit (3 of the 4 step_7_diff items needed no PRD change):
- Item 1 (crew buffer <= BUFFER): genuine PRD ambiguity — "must clear by at least a one-day buffer" reads as "exactly one day is clear/allowed," contradicting "within one day ... is a collision." Impl pins exactly-one-day as a collision. Edited.
- Item 2 (storage-fee test deletions): impl compute_storage_fee (flat 15000 at ≤20 STORED units, +600/unit overage) matches PRD §3.3 verbatim. Deletions are an unreachable-precondition collapse, already determined by existing PRD prose. No edit.
- Items 3 & 4 (proposal-accept OCC / sibling-already-accepted): pure fixture bugs. Impl follows PRD §2.6/§2.7/§3.2 exactly — OCC (priority 7) before state guard (priority 8) before the ERR_PROPOSAL_ALREADY_DECIDED business rule. The "either ERR_PROPOSAL_ALREADY_DECIDED or ERR_INVALID_STATE" relaxation is already implied by §2.6's priority ordering. No edit.

Pre-edit search log (item 1, the only edit):
- (a) Subject: whether a gap of exactly one day between the requested scheduled_date and an existing crew window is a collision or clear.
- (b) Impl paths enumerated/read: routes/work_orders.py:86-107 _crew_double_booked (sole collision check, symmetric abs(...) <= BUFFER, treats each work order's single scheduled_date as a point "window," skips CANCELLED and null-date orders); its sole callsite routes/work_orders.py:128-129; BUFFER = timedelta(days=1) at :19. Grepped all of routes/ and services/ for double_book/BUFFER/scheduled_date — confirmed no other collision/buffer logic exists. compute_crew_utilization_planned/_actual group by scheduled_date but perform no buffer comparison, so they are unaffected.
- (c) Wording adjustment: Kept "closed-interval, buffer-strict check" verbatim. Replaced "at least a one-day buffer" with "more than a one-day buffer" and "within one day ... is a collision" with "absolute gap ... one day or less is a collision; ... exactly one day before or after." Used "absolute gap" and "before or after" to match the symmetric abs(...) so the wording does not narrow the rule to only the after-direction.

## Step 9: Complete PRD — 2026-06-26T19:45:16.000Z

Produced workspace/PRD_COMPLETED.md as a minimal patch over PRD_FINALIZED.md, pinning every PRD ambiguity/mismatch against implementation/.

File metrics: line count 291 → 291 (unchanged); char count 46,498 → 48,038 (+1,540); changed lines: 8 (all in-paragraph inserts/revisions; no new paragraphs, no new sections).

Counts: ambiguity-pins 7, mismatch-revisions 1.

Changes:
- §2.10 The Logical Clock — insert — ambiguity — pinned the clock-setting endpoint's response shape: stores to_iso8601 verbatim and returns it as the single current_utc field in data (not a standard resource) — routes/clock.py:19-20
- §3.1 Contract Lifecycle (propose) — insert — ambiguity — pinned that a propose with no SUBMITTED proposal is rejected with ERR_INVALID_STATE (409) — routes/contracts.py:130-131
- §3.1 Contract Lifecycle (sign) — insert — ambiguity — pinned that a sign where the count of ACCEPTED proposals is not exactly one is rejected with ERR_INVALID_STATE (409) — routes/contracts.py:148-149
- §3.4 Crews/Work Orders (schedule) — insert/revise — mismatch — pinned the fixed evaluation order of scheduling preconditions (UNSCHEDULED state guard → crew double-booking → contract-ACTIVE → at-least-one-visit), correcting the PRD's implied "contract-first" ordering, and named the empty-visit error as ERR_INVALID_STATE (409) — routes/work_orders.py:122-139
- §3.6 Off-Season Storage (check-in) — insert — ambiguity — pinned that a check-in whose owning contract is not SIGNED/ACTIVE is rejected with ERR_INVALID_STATE (409) — routes/storage.py:180-181
- §3.9 Renewal (create offer) — insert — ambiguity — pinned that a create when the contract is not ACTIVE or a DRAFT/SENT offer already exists is rejected with ERR_INVALID_STATE (409) — routes/renewal.py:57-65
- §3.9 Renewal (send) — insert — ambiguity — pinned that a send whose offer is not DRAFT or whose parent is not RENEWAL_OFFERED is rejected with ERR_INVALID_STATE (409) — routes/renewal.py:113-117
- §3.9 Renewal (accept, mint new contract) — insert — ambiguity — pinned the minted contract's field shape: copies old client_id, contract_type, early_bird_deadline, custom_design_surcharge_cents; leaves install_fee_cents/storage_fee_cents/early_bird_discount_cents null — routes/renewal.py:149-162
- §3.9 Renewal (expire) — insert — ambiguity — pinned that an expire at or before expires_at (clock not strictly past) is rejected with ERR_INVALID_STATE (409) — routes/renewal.py:193-199

Deliberate non-changes: all pricing/routing/settlement formulas already match impl exactly. §3.7 manual-replenishment RestockOrder prose left untouched (no manual restock-create endpoint exists; prose remains true as a field-shape statement).
