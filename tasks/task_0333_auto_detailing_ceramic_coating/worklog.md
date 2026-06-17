# Worklog — task_0333_auto_detailing_ceramic_coating

## Step 1: Create Task Directory — 2026-06-13T15:47:31.000Z

Created `tasks/task_0333_auto_detailing_ceramic_coating/` and `tasks/task_0333_auto_detailing_ceramic_coating/workspace/` (exact pre-assigned name, no index scan/auto-increment per orchestration directive).

## Step 2: Generate Scaffold (Expert) — 2026-06-13T16:12:15.000Z

All three files are in place, valid, lint-clean, and the file split is honored. The scaffold for task_0333 is complete.

Generated a complete Expert-band scaffold for **Auto Detailing & Ceramic Coating**:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** primary archetype `temporal_windowing` blended with `pricing_engine`; topology `flat`; state-machine shape `parallel`; role model `peer_roles`; layers: optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation, rate/threshold triggers.

**Scaffold contents:**
- **Entities: 11** — Customer, Membership, ServiceBay, MobileUnit, PackageCatalog, VehicleSizeRate, AddOn, Appointment, AppointmentAddOn, JobPhoto, ReworkClaim.
- **State machines: 4** — Appointment carries TWO parallel dimensions (`work_status` BOOKED→…→RELEASED with CANCELLED/NO_SHOW, and `payment_status` UNPAID→DEPOSIT_HELD→PAID→REFUNDED); Membership is cyclic (ACTIVE↔renew/past-due loops); ReworkClaim is branching (approve/reject). Plus 2 concurrency rules (OCC on ServiceBay.version and ReworkClaim.version, both 412).
- **Calculations: 8** — appointment_total (dual provisional/final variant), customer_loyalty_tier (dual chronological/forward variant), occupancy_window, bay_overlap_check (half-open), mobile_overlap_check (travel-buffer), membership_credit_ledger, payment_ledger, guarantee_window_check. All money in integer cents, round_half_up; literals pre-computed.
- **Validations: 20** (priority-ordered, spanning auth/existence/state/business_safety/fiscal/constraint/temporal/referential).
- **Endpoints: 50** (driven by the rich parallel + cyclic + branching state machines, catalog config, and FK reverse-reachability GETs; includes one `/_clock/set_current_utc` test-driving endpoint).
- **Error catalog: 21.**
- **RBAC roles: 4** — Customer (entity_backed:Customer), Detailer (opaque), Scheduler (opaque), ShopManager (opaque hierarchical override).

**Design instance counts:**
- §1.8: **18 difficulty instances** — 9 rule_ids × 2 instances each.
- §1.9: **48 corner instances** — 42 active + 6 `excluded_because` stubs, across all 9 claim-extraction-guide sections.

**Verification:** `scaffold_lint.py` reports VERDICT: clean lint (526 calls scanned). All grounds references resolve; all instance names unique; file-split honored.

## Step 3: Copy Shared Files — 2026-06-13T16:12:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T16:18:19.000Z

Generated `workspace/PRD.md` — **291 lines, ~6,880 words**.

### Section structure
- **§1 Introduction** — framing pricing, scheduling, guarantees/loyalty + four roles.
- **§2 Global Specifications** (9 subsections): 2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties & Object Identity, 2.5 Nested Retrieval & Referential Integrity, 2.6 Monetary Amounts/Minutes/Rounding, 2.7 Optimistic Concurrency Control, 2.8 Two Parallel Dimensions of an Appointment, 2.9 Validation Ordering.
- **§3 Business Logic** (9 subsections): catalog/resources, booking pricing + occupancy window, bay overlap & mobile travel buffer, work lifecycle (photos/add-on lines), memberships & credit ledger, loyalty tiers, money movement & final-price cascade, rework guarantee, clock test-driving.
- **§4 Endpoint Definitions** — 4-column table, 50 rows + filters paragraph.
- **§5 Error Code Catalogue** — 21 errors.

### Hard contract reports
- Contract 1 — Field-Name Coverage: 67/67 required present, 0 missing. PASS
- Contract 2 — Rule Coverage: validations ordering, OCC (2), all state transitions, 8 calculations, side-effects/cascades all expressed, 0 missing. PASS
- Contract 3 — §3 Path Purity: 401 backtick tokens scanned; 0 path/method tokens in §3. PASS

### Coverage confirmation
Every entity, both parallel Appointment state machines + Membership + ReworkClaim machines, all 8 calculations (with pinned evaluation order, round-half-up at each step), all 20 priority-ordered validations, all 50 endpoints, all 21 errors, all 4 roles covered. §2.2 emitted byte-for-byte from canonical source. The two withheld design files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-06-13T16:35:27.000Z

Generated complete test infrastructure under a strict design-index-only contract.

### Test helpers (Stage 1) — 9 files in `test_helpers/`
`types.py`, `api_client.py` (incl. `set_clock`), `api_errors.py`, `assertions.py` (incl. payment & credit conservation checkers), `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_customer_headers` + opaque-role headers), `fixtures.py` (catalog seeding, membership activation, booking, full lifecycle to RELEASED, rework-claim setup), `__init__.py`.

### Test suite (Stage 2) — `conftest.py` + 6 test files, **78 tests**
- Queue A (Difficulty): **36 tests** — all 18 difficulty instances ×2.
- Queue B (Corner): **42 tests** — all 42 non-stub corner instances ≥1.

### Instances skipped
- 6 corner `excluded_because` stubs not translated (correct by spec): `appointment_initial_work_status_is_booked`, `loyalty_threshold_at_exactly_silver_boundary`, `stale_bay_version_alone_returns_stale_bay_version`, `list_rework_claims_filtered_by_original_appointment_fk`, `derived_outstanding_reconciles_after_final_price_drop`, `immediate_consistency_provisional_total_visible_in_create_response`. All 6 cross-refs resolve to real difficulty instances owning the assertion.
- `appointment_default_use_membership_credit_false` translated but asserts only the PRD-derivable outcome (`credit_applied_cents == 0` w/ no active membership), not the un-stated server-side default field echo.

No instance dropped for lack of PRD coverage. Every test carries exactly one well-formed `Design:` tag; no skip/xfail. All 119 PRD quotations (≥6 words) pass literal whitespace-normalized grep of PRD.md (C1 verbatim check passes for all 78 tests).

## Step 6: Generate Implementation — 2026-06-13T16:35:27.000Z

Built a complete Python + Flask implementation at `workspace/implementation/` (~20 source files + launcher, ~1950 LOC).

### Files
`start.sh` (guarded-install foreground launcher), `app.py`, `db.py` (in-memory store), `clock.py` (test-drivable logical clock), `timeutil.py`, `errors.py`, `response.py`, `serialize.py`, `auth.py` (header auth + RBAC + ownership), `validation.py`, `money.py` (round-half-up decimal), `domain.py` (pricing/occupancy/ledgers/loyalty cascades), `recordutil.py`, and `routes/` (`catalog.py`, `memberships.py`, `appointments.py`, `transitions.py`, `rework.py`, `clock_route.py`).

### Endpoints
All **50** routes from PRD §4 table.

### Storage
In-memory only — one Python dict per entity type keyed by UUID, plus monotonic `_seq` for stable creation-ascending ordering. Versioned resources carry created_at/updated_at/version; the three flat catalogs carry only id/created_at. State at module scope, nothing seeded.

### Clock test-driving
`clock.now()` returns module-level `_override` when set (via `POST /detailing/_clock/set_current_utc`, Scheduler/ShopManager only), else real UTC. All time gates read `clock.now()`. Endpoint mutates no business resource, returns `data: {}`.

### Startup contract — confirmed
`start.sh` reads `$PORT` (default 10000), `app.run(host="0.0.0.0")`, foreground via `exec python3 app.py`, guards pip install behind flask import check. Fresh boot: every entity store reads `total_count: 0`.

### Self-verification
~90 behavioral assertions across five smoke suites passing (validation ordering, member-discount pricing, credit ledger conservation, SHOP vs MOBILE occupancy windows, bay half-open overlap + OCC, cure gating, payment conservation, loyalty tier rise/fall, no-show forfeit vs cancel refund, full rework-guarantee flow).

## Step 7: Test-Iterate-Fix Loop — 2026-06-13T16:48:21.000Z

All tests pass cleanly across the full 8-round parallel stability sweep. **Final: 77/77 passing in all 8 rounds** (orchestrator re-verified the sweep independently; results.{1..8}.json persisted in implementation/).

**Iterations run:** 2 sweeps. Initial baseline: 68/78 passing (10 failures, fully stable/non-flaky). After fixes: 77/77 passing in all 8 rounds.

**Tests deleted (1):**
- `test_rework_approve_blocked_when_original_not_released` (test_05) — STEP 1b unreachable-state collapse. The asserted approve-time guard ("original appointment is RELEASED") is unconstructable under a PRD-faithful impl: PRD §3.8 filing requires the original to have reached RELEASED, and RELEASED is terminal, so no legal path produces a filed claim whose original is non-RELEASED at approve time. Filing guard preempts the approve guard. Scaffold rule: `Difficulty/cross_entity_state_dependency/rework_approve_blocked_when_original_appointment_not_released`.

**Fixes applied to `test_suite/` (all TEST BUGS):**
- `test_01_pricing_and_totals.py`: `_seed_full_suv_member_with_two_addons` now seeds the WASH package (PRD §3.5 activation values wash credit from WASH row; omitting it made activation 500). Fixed `test_final_total_diverges_after_lapse_and_skip` to advance clock to `2026-07-16T08:00:00Z` before mark-past-due/lapse (PRD §3.5 gates both on cycle_start + 30d). Corrected one timestamp literal to PRD §2.4-mandated 3-fractional-digit `.000Z`.
- `test_02_scheduling_and_occupancy.py`: corrected 4 occupancy/release timestamp literals to `.000Z`.
- `test_03_work_payment_lifecycle.py`: corrected `cycle_start_utc` literal to `.000Z`.
- `test_06_crud_rbac_listing.py`: corrected `occupancy_end_utc` literal to `.000Z`.
- `test_05_validations_and_priority.py`: rewrote `test_rework_claim_at_window_end_rejected` to be PRD-faithful — filing at window end now succeeds (PRD §3.8: claim begins SUBMITTED; records filed_within_window=False), and the `ERR_GUARANTEE_EXPIRED` rejection is asserted on **approve**, the endpoint PRD pins it to.

**Fixes applied to `implementation/` (1):**
- `routes/rework.py` `approve()`: moved the `expected_claim_version` OCC check **before** the SUBMITTED state check. PRD §2.7 walks the double-approve case and pins the outcome to `ERR_STALE_CLAIM_VERSION`, requiring version check to precede state check.

The implementation's timestamp format (`.000Z`) was correct per PRD §2.4/§2.2 throughout; the 7 failing timestamp assertions were test-literal bugs, not implementation bugs.

## Step 8: Finalize PRD — 2026-06-13T16:52:43.000Z

PRD_FINALIZED.md created and is **identical to PRD.md (0 edits, 0% delta, 291 lines)**. After auditing every step_7_diff item against the implementation, no PRD edits were warranted — each item is either a pure fixture/test bug or behavior the existing PRD already uniquely determines.

### Per-item analysis
- **Test deletion** (rework approve-blocked-when-not-released): reachability collapse, not a PRD silence. PRD §3.8 already requires filing original to have reached RELEASED; §3.4 makes RELEASED terminal. No pin needed.
- **Impl fix** (rework.py approve() OCC-before-state): PRD §2.7 already uniquely determines this — its double-approve walkthrough pins the stale second approve to `ERR_STALE_CLAIM_VERSION`, which requires version check before state check. Fix brought code into line with existing prose; no PRD change.
- **Test-suite fixture fixes** (WASH seeding, clock advance, .000Z literals, window-end rework rewrite): all test bugs; PRD §3.5/§3.8/§2.4/§2.2 already pin the relevant behaviors.

### NO-NEW-MISMATCH note
Key global-enumeration finding: PRD §2.7 describes each OCC guard separately and makes NO universal "version-always-first" claim. The membership-cancel path (memberships.py:167-170) runs state-check *before* version-check — the opposite order. Had a Step 8 edit pinned "version checked first" universally, it would have introduced a brand-new mismatch against the membership path. Confirming this consistency is why 0 edits was the correct outcome.

## Step 9: Complete PRD — 2026-06-13T17:00:10.000Z

PRD_COMPLETED.md created via full PRD-vs-implementation scan.

**Source vs output:** PRD_FINALIZED.md = 291 lines / 48,068 chars → PRD_COMPLETED.md = 291 lines / 50,265 chars. Char delta: **+2,197** (6 in-paragraph edits; no new lines, sections, or paragraphs).

**Counts:** ambiguity-pins: 6 · mismatch-revisions: 1

- **§2.3 Pagination** — insert — ambiguity — non-integer `limit`/`offset` (not just out-of-range) rejected with `ERR_VALIDATION` — validation.py:84-92.
- **§3.1 Catalog/Resources** — insert — ambiguity — every "must be unique" violation (package tier, vehicle_size, addon_code, bay_code, unit_code, customer email) rejected with `ERR_INVALID_REQUEST` after per-field well-formedness — catalog.py:30,107,140,167,193,244.
- **§3.2 Booking** — insert — mismatch — impl resolves resource FK (service_bay_id/mobile_unit_id) only after tier/vehicle_size/location_mode/scheduled_start_utc well-formedness (customer_id resolved before); pinned that ordering split vs literal §2.9 "all FKs first" — appointments.py:54-80.
- **§3.2 Booking credit** — insert — ambiguity — `use_membership_credit` optional, defaults false when omitted/null — appointments.py:65.
- **§3.4 Add-on line add** — insert — ambiguity — add to non-BOOKED appointment is `ERR_INVALID_STATE`; per-appointment addon_code duplicate is `ERR_INVALID_REQUEST`; full add-line cascade (reseed final_total_cents, recompute outstanding + projected) — appointments.py:262-289.
- **§3.4 Set-line-status** — insert — ambiguity — no work-status precondition; changes only line_status (no totals/occupancy recompute); bumps both appointment and line version — appointments.py:307-326.
- **§3.5 Membership cancel** — insert — ambiguity — `ERR_INVALID_STATE` state gate evaluated before `expected_membership_version` match (state beats stale version) — memberships.py:167-170.

Left unchanged (already pinned or degenerate/unobservable): rework-approve version-before-state (§2.7/§3.8), bay-version bump on booking (§2.7), no-show/cancel occupancy reuse (§3.3), clock empty-object response (§2.2/§4), missing-catalog-row preconditions.

---

## Pipeline Complete

All 9 steps finished. Final state: **77/77 tests passing across all 8 parallel stability rounds** (results.{1..8}.json persisted in workspace/implementation/). Task directory contains SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/, test_suite/, and workspace/ with INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, and implementation/.
