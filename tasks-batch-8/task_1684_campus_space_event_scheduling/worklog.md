# Worklog — task_1684_campus_space_event_scheduling

## Step 1: Create Task Directory — 2026-08-14T07:33:00.000Z

Task directory `tasks/task_1684_campus_space_event_scheduling/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions. Verified both exist.

## Step 2: Generate Scaffold — 2026-08-14T08:30:00.000Z

All three scaffold artifacts are complete and lint-clean. Summary of what was generated in `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/`:

**Counts (SCAFFOLD.yaml)**
- Entities: 10 (Organization, Room, TermWindow, AcademicBlock, SchedulingRun, EventReservation, ServiceOrder, ServiceCrew, Invoice, AccessGrant)
- State machines: 9 (all entities except ServiceCrew; EventReservation has 10 states with a CONFIRMED→BUMPED→APPROVED→CONFIRMED cycle, ServiceOrder has a QUOTED↔NEEDS_REVISION loop)
- Calculations: 10 (occupied-interval, priority_score, per-bucket room charge, cancellation fee tiers, provisional/final invoice, scheduled/realized utilization, crew load overlap, standing thresholds, greedy placement with bump fallback, deposit refund)
- Validations: 10 priority tiers (auth → authz → existence/ownership-masking → request shape → OCC 412 → state 409 → safety → temporal → constraint → fiscal 402)
- Endpoints: 51 (flat topology under `/campus`, plus `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Error catalog: 30 entries; Roles: 5 (OrgRequester entity-backed by Organization with cross-org 404 masking; Scheduler/ServiceCoordinator/FacilitiesManager/FinanceAdmin opaque; segregation-of-duties between event approver and invoice waver)
- Concurrency rules: 2 OCC (run-create vs TermWindow.version, reservation-create vs Room.version, both 412 ERR_STALE_VERSION)

**§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml): 19 instances** — every rule ≥2, Rule 2 has 3 covering all three modes (multi-input priority score with conditional bonus; per-bucket round-then-sum with a proven 1¢ divergence at rate 9999 × 3 peak buckets: 47496 vs 47495; pinned score-then-sort-then-assign-then-bump evaluation order). Cascades: finalize chain of depth 4 (run→block→event→invoice→org balance) and daily-close chain of depth 4 (close→NO_SHOW→strike count→standing→auto-decline). All numeric asserts are precomputed literals (47496/48446, 1458/1591 bps, 18750 late-return no-show total, etc.).

**§1.9 (SCAFFOLD_CORNER_DESIGN.yaml): 50 active instances + 6 excluded stubs**, across all nine claim-guide sections.

**Design decisions for downstream steps**
- Logical clock + `POST /campus/ops/daily-close` (8 pinned steps in fixed order) drives all time-based transitions; no wall-clock dependence.
- Rates are pinned on the event at approve/rebook time (version-pinning layer): room PATCHes never reprice approved events; rebook re-pins from the new room.
- Bump shield: CONFIRMED events are bumpable only when `start_at - now >= 72h` (strict < is shielded) AND no ISSUED/OVERDUE grants; REQUESTED/APPROVED always bumpable. Unplace never restores bumped events.
- Two overlap semantics deliberately contrasted: Room = exclusive with asymmetric post-event buffer (half-open, buffer not billed); ServiceCrew = aggregate capacity, half-open, no buffer.
- Chain-replay fixes applied during authoring: events to be bumped are created *after* the term-advancing close (so decision-expiry doesn't kill them first); REQUESTED/BUMPED cancels carry no invoice; cancel-from-BUMPED added (reason BUMPED, fee 0) so cancel_reason's enum is closed; waive capped at `total - paid - waived` (ERR_OVERPAYMENT) so PAID's equality transition is well-defined.
- `scaffold_lint.py` verdict, verbatim: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." (633 calls scanned; 0 violations.) Also verified separately: zero unbound `${var}` placeholders, 75 unique instance names across both design files, zero dangling grounds refs, no forbidden race vocabulary.

Orchestrator verification: all three files exist (SCAFFOLD.yaml 1410 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 667 lines, SCAFFOLD_CORNER_DESIGN.yaml 1100 lines).

## Step 3: Copy Shared Files — 2026-08-14T08:31:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1684_campus_space_event_scheduling/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T08:50:00.000Z

All three hard contracts pass. The PRD is complete and verified. Here is the final summary.

## Generation Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/workspace/PRD.md` — **343 lines**

### Section list
- **§1. Introduction** (2 paragraphs — business context + system goals)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (headers, 5 roles, identity semantics per role)
  - 2.2 API Response Structure (**byte-identical to the fixed verbatim block**, verified programmatically)
  - 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending, meta fields)
  - 2.4 The Logical Clock and the Daily-Close Checkpoint (clock start 2026-08-01T00:00:00Z, forward-only, pinned 8-step close order + 8 response counters)
  - 2.5 Common Resource Properties (`id` UUID, `created_at`/`updated_at` 3-fractional-digit ISO 8601 UTC, `version`)
  - 2.6 Occupancy Intervals, Turnaround Buffers, and Conflict Semantics (half-open, asymmetric buffer, block recurrence)
  - 2.7 Money, Rates, and Rounding (integer cents, round-half-up, three rate cards, peak definition)
  - 2.8 Optimistic Concurrency Control (both OCC rules, `ERR_STALE_VERSION` 412, stale-version framing only)
  - 2.9 Validation Priority Order (all 10 tiers as an explicit ordered cascade)
  - 2.10 Nested Resource Retrieval and Ownership Masking
- **§3. Business Logic & Workflows** (7 subsections): 3.1 Organizations/Standing/Eligibility, 3.2 Room Inventory/Rate Cards/Outages, 3.3 Terms/Academic Blocks/Placement Run, 3.4 Event Reservation Lifecycle, 3.5 Service Orders/Crew Assignment, 3.6 Invoicing/Payments/Finance Controls, 3.7 Access Grants/Key Inventory/Deposit Forfeiture
- **§4. Endpoint Definitions** — 51-row table, 4 columns only (Method, Path, Description, Authorized Role(s))
- **§5. Error Code Catalogue** — 30-row table, 2 columns only (Error ID, HTTP Status Code)

### Hard Contract Reports

```
Field coverage check (Contract 1):
- entities[].fields + endpoint inputs/query params + enum values + roles + headers + error ids:
  222 required, 222 present, 0 missing (two passes run; pass 1 found LOST/RETURNED/REVOKED missing, repaired)
Status: PASS
```

```
Rule coverage check (Contract 2):
- validations[] with priority: 10 checked, 10 expressed as an ordered cascade in §2.9, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_term_version/expected_room_version + ERR_STALE_VERSION 412 named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed (from/to states, preconditions paired with error ids, side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (incl. pinned bucket-rounding order with the 37497-vs-37496 example, cancel-tier boundaries, placement 3-pass order), 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 51 checked, 51 expressed, 0 missing
- entities[].fields[] structured content: all defaults/initial values/null-until semantics reconstructible, 0 missing
- sibling-branch symmetry: 11 groups checked (cancel reasons, fee tiers, invoice variants, utilization variants, quote transitions, deposit branches, placement branches a/b/c, precedence tiers, 8 feature weights, rate cards), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 583
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional scans: zero fuzzy/approximating words, zero operator/pseudocode symbols in prose, §2.2 byte-identical to the canonical source file.

### Zero-Silence Rule coverage audit (scaffold → PRD mapping)
- **Entities (10)** → fields scattered across §2.5 (common fields), §3.1 (Organization), §3.2 (Room + utilization outputs), §3.3 (TermWindow/AcademicBlock/SchedulingRun), §3.4 (EventReservation), §3.5 (ServiceOrder/ServiceCrew), §3.6 (Invoice), §3.7 (AccessGrant)
- **State machines (9, 41 transitions)** → Organization.standing §3.1; Room.status §3.2; TermWindow/AcademicBlock/SchedulingRun §3.3; EventReservation (11 transitions incl. expiry, no-show, completion) §3.4; ServiceOrder (8) §3.5; Invoice (5) §3.6; AccessGrant (5) §3.7; clock-driven transitions pinned in §2.4
- **Concurrency rules (2)** → §2.8, reinforced at §3.3 (run create) and §3.4 (event create)
- **Calculations (10)** → occupied_interval §2.6; priority_score + scheduling_placement §3.3; standing_threshold §3.1; room_charge/cancellation_fee/final_invoice_total §3.4+§3.6; utilization_bps §3.2; crew_load_overlap §3.5; deposit_refund §3.7
- **Validations (10 priorities)** → §2.9 ordered cascade + trigger conditions placed next to each guarded workflow in §3
- **Endpoints (51)** → §4 table; request semantics only in §3 narratives
- **Errors (30)** → §5 table (IDs + statuses only); trigger conditions scattered in §2/§3
- **Roles (5)** → §2.1 incl. identity translations (OrgRequester entity-backed by Organization; other four opaque)

### Notes for downstream steps
- The verification regex must strip fenced code blocks before extracting inline backtick tokens — the §2.2 JSON fences otherwise flip pairing parity and produce garbage matches (cost me one debug cycle).
- Deliberate fidelity choices: (a) `ERR_CAPACITY_EXCEEDED` is stated for event attendance and mirrored for enrollment as a candidate-eligibility guard in placement without inventing a new trigger point; (b) block/run creation against a `CLOSED` term is stated as prohibited with no error ID, matching scaffold silence; (c) the suspension cascade's effect on service orders is left unstated (scaffold-silent) while grant revocation under suspension is stated (scaffold-backed); (d) `approved_by_user_id` is described as recording the acting approver/rebooker to cover rebook-by-owner without contradicting the scaffold's Scheduler phrasing.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, per the hard constraint.

## Step 5: Generate Unit Tests — 2026-08-14T09:20:00.000Z

Generation complete. All artifacts verified. Summary:

## Output

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/test_helpers/`):
- `types.py` — 10 entity TypedDicts + status/role enums (all entities carry common fields per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD endpoint; clock endpoint correctly mounted at root `/_clock/set_current_utc` (outside `/campus`)
- `api_errors.py` — 30-entry `ApiErrorId` catalog + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions, invoice component-sum invariant, key-inventory invariant, `assert_same_instant`
- `factories.py`, `constants.py`, `test_users.py` (opaque operator constants + mandatory `make_org_requester_headers(org.id)` builder for the entity-backed role), `fixtures.py` (clock/close primitives, event/order/grant/invoice walkers, no-show-strike builder, placement-contention and bump-chain composite scenarios)

**test_suite/** — 13 files + `conftest.py`, **83 tests total**.

## Coverage

- **Queue A (Difficulty): 15/17 instances translated, 34 tests** (≥2 per instance; verified by audit).
- **Queue B (Corner): 49/50 non-stub instances translated, 49 tests**; all 6 `excluded_because:` stubs left untranslated with cross-references verified to resolve.

## Skipped instances (PRD-first filter failures)

1. `Difficulty/non_linear_state_machine/event_confirmed_bumped_rebooked_confirmed_cycle` — the recipe rebooks at clock 2026-08-12 with the term in SCHEDULING and the event span (2026-10-05) intersecting term dates; PRD §3.3/§3.4 ("clear of the term priority lock") dictate ERR_TERM_PRIORITY_LOCKED, so the asserted success contradicts the PRD.
2. `Difficulty/priority_pair_validation_conflict/pay_voided_invoice_state_beats_overpayment_fiscal` — PRD internal contradiction: §2.9 tiering (state tier 6 masks money tier 10 → ERR_INVALID_STATE) vs §3.6's explicit "any payment attempted on a `VOIDED` or `REFUNDED` invoice" → ERR_OVERPAYMENT. Two PRD-only readers diverge.
3. `Corner/endpoints/invoices_filtered_list_by_event_and_status` — the claim is `event_id`/`status` list filters, but the PRD never documents filter query parameters for `GET /campus/invoices` (§4 is navigational; §2.3 covers only limit/offset). Not PRD-covered.

## Adjudications worth recording

- **Absolute version literals dropped**: PRD §2.5 pins "increments by one" but never the initial value; OCC/creation tests assert captured relative relations (`v_after == v_before + 1`) instead of recipe literals (==1/2/3).
- **`created_at` value not asserted**: PRD §2.4's list of clock-readers omits `created_at`; the event-create test asserts the clock-derived `decision_deadline` (2026-08-04T00:00:00Z) instead.
- **Instant comparisons** (`assert_same_instant`) replace timestamp string equality, since the PRD pins instants while fractional-digit rendering is mandated only for `created_at`/`updated_at`.
- **Ledger-conservation intermediate literal corrected**: the recipe's `out_mid == 0` contradicts §3.1's balance definition (the second event's live 10000 provisional contributes); tests assert the PRD-derived 20000 → 10000 → 0 progression.
- **DRAFT-phase approvals**: placement/cascade fixtures approve events while the term is DRAFT, following §3.3's controlling sentence (lock scoped to "while a term is in SCHEDULING") over §3.4's looser "must be in GENERAL" phrasing; the dedicated term-lock corner test exercises only the unambiguous SCHEDULING (locked) and GENERAL (allowed) phases.
- **No reliance on undocumented list filters**: helpers locate related resources via unfiltered lists + client-side selection.

## Verification

All files compile; pyflakes clean; `pytest --collect-only` collects 83 tests; every test docstring ends with exactly one resolving `Design:` line; 151 quoted spans (≥6 words) all survive whitespace-normalized literal grep against PRD.md; no `skip`/`skipif`/`xfail` markers anywhere.

## Step 6: Generate Implementation — 2026-08-14T09:30:00.000Z

Implementation complete and verified. Here is the summary.

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (no-op once Flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 82 | Flask entry: route registration from the registry, auth ladder rungs 1–2, per-request bump scope, error envelope handlers (404/405 → `ERR_NOT_FOUND`), global RLock |
| `constants.py` | 177 | Roles, enum vocabularies, feature weights, precedence tiers, rate-card mapping, all time/money constants, status sets |
| `clock.py` | 138 | Logical clock + ISO 8601 parsing/rendering |
| `db.py` | 133 | In-memory store (dicts keyed by id), `new_row`/`touch`/`set_fields`, one-bump-per-request versioning |
| `errors.py` | 76 | `ApiError` + full error catalog (id → HTTP status, default messages) |
| `middleware.py` | 69 | Endpoint registry decorator, `Ctx`, `authenticate` (401) / `authorize` (403) |
| `response.py` | 91 | `meta`/`response_type`/`data` envelope, pagination clamping (limit 1–100 default 10, offset ≥ 0) |
| `validate.py` | 236 | Typed field readers (str/int/datetime/HH:MM/enum/array), existence getters (404), OrgRequester ownership masking |
| `serializers.py` | 212 | Per-entity output shaping with computed fields |
| `routes/` (13 files) | 1388 | One module per resource group: clock, organizations, rooms, terms, academic_blocks, scheduling_runs, events, service_orders, service_crews, invoices, access_grants, ops, common |
| `services/` (8 files) | 872 | `intervals.py` (occupancy/conflicts/bumpability), `pricing.py` (Decimal round-half-up money math), `invoices.py` (provisional/final variants), `cascade.py` (bump + suspension), `placement.py` (3-pass waterfall), `daily_close.py`, `derive.py` (standing/balances/key counters) |

Total: 3,602 lines.

## Architecture notes

- **Logical clock**: module-level `LogicalClock` in `clock.py`, pinned at `2026-08-01T00:00:00Z` at import (fresh process per test ⇒ fresh clock), never reads wall-clock. `POST /_clock/set_current_utc` (Scheduler-only) requires a strictly-later instant (else `ERR_INVALID_REQUEST`) and echoes `to_iso8601` verbatim as `current_utc`. All deadlines/window rules read this clock. Server-written timestamps render with exactly three fractional digits + `Z`; caller-supplied datetimes are stored raw and echoed byte-for-byte.
- **Daily-close** (`services/daily_close.py`): implements the pinned 8-step order — term advance (loops per term so DRAFT→SCHEDULING→GENERAL/CLOSED settle in one run) → room auto-return → REQUESTED expiry → APPROVED expiry (provisional invoice VOIDED) → no-show marking (strike, standing recompute, suspension cascade when count hits 3) → completion (final invoice) → grants OVERDUE → balances (derived on read). Returns the 8 pinned counters.
- **OCC**: only the two declared endpoints accept version fields. `expected_term_version` on run create and `expected_room_version` on event create are checked at ladder rung 5 (after shape, before state) → `ERR_STALE_VERSION` 412; successful creates bump the parent's `version`. `version` starts at 1; every mutation touches `updated_at` + `version` exactly once per request per row (including cascade/daily-close mutations).
- **Money**: all integer cents via `Decimal` ROUND_HALF_UP — per-bucket rounding for room charges (verified: rate 9999 × 4 peak buckets = 49996), tiered cancellation fees on the pinned invoice base (72h/24h boundaries inclusive as specified), 2% EXTERNAL surcharge, 50%/100% deposit forfeits.
- **No seeding / no persistence**: store starts empty on every boot (grep-verified: no sqlite, no file I/O, no seed functions); every entity is built through the declared API surface.

## Boot + behavior verification

- `bash start.sh` boots cleanly and serves within ~1s (verified repeatedly, including via the exact harness contract).
- Three fresh-boot scenario suites + a pagination probe — **188 assertions, all passing**: auth ladder (401/403), envelope shapes, OCC 412s, peak-bucket pricing, pinned rates, provisional recomputation (incl. NEEDS_REVISION exclusion), confirm gates (insurance/confirm-window/probation prepayment 402), cancellation tiers (free/half/full, exact boundaries, ADMIN/BUMPED free), no-show → PROBATION → SUSPENDED cascade + reinstate, placement waterfall (scoring, sort, best-fit, bump cascade, rebook re-pinning, `ERR_TERM_ALREADY_FINALIZED`), term priority lock (blocked in SCHEDULING, allowed in DRAFT/GENERAL), out-of-service bump/shield (`ERR_ROOM_BLOCKED`), capacity-cut bump vs `ERR_ROOM_EDIT_BLOCKED`, key inventory (lowest-free-slot, `ERR_NO_KEYS_AVAILABLE`, lost-slot retirement, invariant), crew category/shift/capacity checks with half-open boundary, check-in window inclusivity, utilization (merged intervals, outage denominator, null bps at denominator 0), invoice pay/waive/refund (SoD 403, overpayment 422, refund cap), ownership masking as 404, OrgRequester list scoping, and pagination defaults/clamping.

One deliberate spec call worth noting: the PRD's priority-lock prose (only SCHEDULING blocks approve/rebook; DRAFT does not) was followed over the scaffold's stricter "must be GENERAL" precondition, per the PRD-wins rule.

## Step 7: Run Tests and Iterate — 2026-08-14T09:45:00.000Z

Clean sweep: all 8 rounds passed 83/83 with zero failures. Exiting with the summary.

## Summary

**Iterations run:** 2 (sweep 1: 75/83 per round with the same 8 deterministic failures in every round; sweep 2 after fixes: 83/83 × 8 rounds, zero flaky failures).

**Tests deleted:** none. Every failing test asserted a rule stated verbatim in PRD.md (§2.6 half-open buffered occupancy, §2.9 tier order, §3.3 block validation/unplace/double-finalize, §3.4 capacity screening and insurance gates, §3.6 bucket billing and refund ledger). All 8 failures were test-artifact bugs, not implementation bugs and not PRD-silence cases.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/test_suite/test_03_terms_blocks_and_placement.py` — added missing `self` to all 8 class-based test methods. They were declared `def test_x(api):`, so Python bound the class instance to `api` and pytest never injected the fixture; the 3 methods that call `api.*` (`test_block_with_start_not_before_end_is_rejected`, `test_unplace_does_not_restore_bumped_events`, `test_second_finalize_rejected_term_already_finalized`) died with `AttributeError: 'TestX' object has no attribute ...`. Assertions themselves were PRD-faithful; only the signatures were broken.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/test_suite/test_06_booking_conflicts_and_occ.py` — `test_buffered_edge_moves_with_the_rooms_buffer`: the colliding E3 payload spanned 11:44–12:00 (16 minutes), violating PRD §3.4's 30-minute minimum, so tier-4 `ERR_DURATION_OUT_OF_RANGE` correctly masked the tier-9 `ERR_ROOM_NOT_AVAILABLE` the test targets. Extended E3's `end_at` to 12:15 (31 minutes) so the §2.6 buffered-conflict rule is what surfaces.

3. `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/test_suite/test_08_invoices_payments_finance.py` — `test_refunds_accumulate_and_refund_only_at_full_equality`: setup used the default 1-hour event window (14:00–15:00), which bills one bucket at 5000 = 5000 under PRD §3.6's per-bucket billing, contradicting the test's "two off-peak buckets at 5000 → 10000" premise. Extended the event to 14:00–16:00 (two off-peak Monday buckets, total 10000), keeping all refund assertions (10001 reject, 4000 partial stays PAID, 6000 completes REFUNDED) intact.

4. `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/test_suite/test_11_cascades_and_noshow.py` — added `room_overrides={"capacity": 100}` at two setup call sites (`test_coverage_below_floor_blocked_exactly_at_floor_allowed` and the shared `_setup_expired_window_external` helper used by `test_expired_insurance_and_expired_window_reports_insurance` and `test_short_coverage_and_expired_window_reports_insurance`). They created events with `expected_attendance` 80 against the default room capacity 30, tripping PRD §3.4's `ERR_CAPACITY_EXCEEDED` screen during setup before the insurance gate under test could be exercised.

**Fixes applied to `test_helpers/`:** none — the factories, fixtures, role-header builders, and assertion library were all consistent with PRD; the bugs were at test-function call sites and signatures.

**Fixes applied to `implementation/`:** none — verified the implementation was already PRD-faithful on every failure path (validation tier ordering in `routes/events.py`, per-bucket round-half-up pricing in `services/pricing.py`, capacity screening, placement/unplace/double-finalize semantics).

## Step 8: Finalize PRD — 2026-08-14T09:55:00.000Z

All verification complete. The constants confirm the exact PRD-pinned values (30-minute floor, 8-hour ceiling, 18:00 peak start, 100000000-cent coverage floor), and the copy is byte-identical.

## Summary

**PRD_FINALIZED.md produced** at `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/workspace/PRD_FINALIZED.md` — a byte-identical copy of PRD.md. **Zero edits were warranted.**

**Line counts:** PRD.md 342 lines, PRD_FINALIZED.md 342 lines — 0.0% delta.

### Why no edits

Every `<step_7_diff>` item is a pure test-artifact bug whose target behavior the PRD already pins verbatim. I independently confirmed PRD-implementation agreement on each path (not just trusted the diff), so per the hard scope ("every PRD edit must trace to a specific fix revealing PRD-silence or PRD-mismatch — nothing else") there is nothing to patch.

### Per-item verification log (subject / impl paths enumerated / outcome)

1. **test_03 signature fixes (`self` missing)** — (a) Subject: block window validation, unplace semantics, double-finalize rejection. (b) Enumerated: `/workspace/implementation/routes/academic_blocks.py:35-52` (`ERR_BLOCK_WINDOW_OUT_OF_TERM` on start ≥ end, empty `days_of_week`, no in-term instance), `academic_blocks.py:102-109` (unplace clears `assigned_room_id`/`scheduling_run_id` to `UNPLACED`, bumped events untouched), `/workspace/implementation/routes/scheduling_runs.py:73-91` (DRAFT-only → `ERR_INVALID_STATE`, non-SCHEDULING term → `ERR_TERM_PRIORITY_LOCKED`, existing FINALIZED run → `ERR_TERM_ALREADY_FINALIZED`, in that tier order). (c) Outcome: no behavior involved beyond what PRD §3.3 states verbatim; the tests quote §3.3 in their docstrings. No edit.

2. **test_06 buffered-edge payload (16 → 31 minutes)** — (a) Subject: §2.6 half-open asymmetric buffered occupancy vs. §3.4 duration floor and §2.9 tier order. (b) Enumerated: `/workspace/implementation/services/intervals.py:21-34` (strict half-open `overlap`, buffer appended after teardown only), `/workspace/implementation/routes/events.py:99-133` (duration check at rung 4 with `MIN_EVENT_MINUTES=30`/`MAX_EVENT_HOURS=8` from `constants.py:94-95`, capacity/feature/conflict at rung 9), plus the same `_room_gates` ordering reused by approve (`events.py:210`) and rebook (`events.py:342`). (c) Outcome: PRD §2.6, §2.9, §3.4 pin all of it verbatim; the 16-minute fixture violated the pinned 30-minute floor, masking the tier-9 conflict. No edit.

3. **test_08 refund setup (1-hour → 2-hour window)** — (a) Subject: §3.6 per-bucket billing and refund ledger. (b) Enumerated: `/workspace/implementation/services/pricing.py:34-49` (hour-aligned buckets, every touched bucket = one full hour, round-half-up per bucket then sum; `PEAK_HOUR_START=18`, `constants.py:99`), `/workspace/implementation/routes/invoices.py:100-116` (refund from PAID/PARTIALLY_PAID only, `amount > paid - refunded` → `ERR_REFUND_EXCEEDS_PAID`, REFUNDED only at full equality). (c) Outcome: PRD §3.6 pins touched-bucket billing and the refund rules verbatim; the fixture's 1-hour premise contradicted the pinned bucket math. No edit.

4. **test_11 capacity overrides (attendance 80 vs. default capacity 30)** — (a) Subject: §3.4 creation-time capacity screen and external insurance gates. (b) Enumerated: `/workspace/implementation/routes/events.py:126-127` (creation screen `expected_attendance > capacity` → `ERR_CAPACITY_EXCEEDED`), the parallel approval/rebook gate at `events.py:65-66`, and the insurance gates at `events.py:246-258` (expiry `>= end_at` inclusive, coverage `>= 100000000` inclusive from `constants.py:109`) ordered at rung 7 before the confirm-window rung 8 (`events.py:260-261`). (c) Outcome: PRD §3.4 pins the capacity screen and insurance floor verbatim, §2.9 pins tier 7 before tier 8. No edit.

**Key finding:** Step 7's fixes were 100% test-side (8 broken method signatures, 2 constraint-violating fixtures, 1 wrong bucket-count premise, 2 missing capacity overrides). The implementation is PRD-faithful on every exercised path, and the PRD uniquely determines every behavior the fixed tests assert — so the correct finalized PRD is the identity patch.

## Step 9: Complete PRD — 2026-08-14T10:05:00.000Z

All edits verified. The completed file is coherent and every change traces to a specific implementation behavior.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1684_campus_space_event_scheduling/workspace/PRD_COMPLETED.md`

**Source:** `PRD_FINALIZED.md` (existed; copied per method step 0). Line counts: 342 → 342 (all edits are inline inserts/revisions; no new lines or sections). Char delta: 55,453 → 59,989 (+4,536 chars), 31 lines altered.

**Counts:** 34 ambiguity-pins, 4 mismatch-revisions.

### Mismatch revisions (PRD prose contradicted impl)

- §3.4 — revise — mismatch — term priority lock: "any intersecting term must be in `GENERAL`" → "no intersecting term may still be in `SCHEDULING`" (impl locks only SCHEDULING terms; DRAFT/CLOSED terms do not lock) — implementation/routes/events.py:46-57
- §3.3 — revise — mismatch — placement free candidates: "no overlap from non-bumpable event occupancy" → "no overlap from any event occupancy, `REQUESTED` demand included" (impl counts REQUESTED events as placement conflicts, forcing the bumpable class and bumping them) — implementation/services/placement.py:86-93, implementation/services/intervals.py:128-142, implementation/constants.py:164-165
- §3.4 — revise — mismatch — cancellation order sweep: "all non-terminal orders move to `CANCELLED`" → fulfilled orders move to `INVOICED` as the invoice finalizes; only the remaining non-terminal orders are cancelled — implementation/services/invoices.py:162-164, implementation/routes/events.py:321-323, implementation/services/cascade.py:21-27
- §2.6 — revise — mismatch — PLACED block instances conflict not only "during academic placement" but also at event approval/rebooking; creation screens committed events + outages only — implementation/routes/events.py:70-73 (include_blocks=True) vs :132 (default False)

### Ambiguity pins (PRD silent; pinned to impl)

- §2.2 — insert — `api_request_id` = `req_` + twenty uppercase alphanumeric chars; `api_request_timestamp` read from the logical clock — implementation/response.py:20-30
- §2.3 — insert — out-of-range/unparsable `limit`/`offset` are clamped (limit→[1,100], default 10; offset→0), never rejected — implementation/response.py:61-84
- §2.3 — insert — list ordering ties broken by creation order — implementation/db.py:122-129
- §2.3 — insert — `has_more` = `offset` + returned-items < `total_count` — implementation/response.py:47
- §2.4 — insert — clock-set rejects unparsable/non-strictly-later target with `ERR_INVALID_REQUEST`; `current_utc` echoes the supplied `to_iso8601` verbatim — implementation/routes/clock.py:12-21
- §2.4 — insert — daily-close counters count affected resources once per run (multi-phase term advance counts once) — implementation/services/daily_close.py:26-44
- §2.5 — insert — `version` starts at 1; `updated_at` equals `created_at` at creation — implementation/db.py:108-119
- §2.5 — insert — both timestamps read the logical clock; a resource touched repeatedly within one request increments `version` exactly once — implementation/db.py:83-94
- §2.5 — insert — server-written instants (decision_deadline, confirm_deadline, checked_in_at, return_deadline, returned_at, finalized_at) render 3-fractional-digit UTC; caller-supplied instants echoed verbatim; bare `YYYY-MM-DD` accepted as UTC midnight — implementation/clock.py:36-99, implementation/serializers.py
- §2.10 — insert — enumerated exact-match list filters per endpoint (blocks: term_id/assigned_room_id/scheduling_run_id/status; runs: term_id/status; events: room_id/requester_org_id/status; orders: event_id/crew_id/category/status; invoices: event_id/org_id/status; grants: event_id/room_id/status); filters apply before pagination (`total_count` is filtered); empty-match → empty page; unknown params ignored — implementation/routes/common.py:7-31 and each route's `mapping=`
- §3.1 — insert — suspension cascade cancels the org's APPROVED events' non-terminal service orders, fulfilled ones included, with `fee_waived` true — implementation/services/cascade.py:56-60
- §3.2 — insert — outage requires an `ACTIVE` room; already-`OUT_OF_SERVICE` → `ERR_INVALID_STATE` — implementation/routes/rooms.py:115-116
- §3.2 — insert — `outage_windows` entries record the supplied `start_at`/`end_at` — implementation/routes/rooms.py:144
- §3.2 — insert — utilization bounds are query parameters; missing/unparsable → `ERR_INVALID_REQUEST` — implementation/routes/rooms.py:175-180
- §3.2 — revise — utilization bps computed on exact durations (sub-minute precision), minute fields floored to whole minutes — implementation/routes/rooms.py:168-169, 213-219
- §3.3 — insert — closed-term block/run creation rejected with `ERR_INVALID_STATE` — implementation/routes/academic_blocks.py:54-58, implementation/routes/scheduling_runs.py:27-28
- §3.3 — insert — block creation in a `GENERAL` term → `ERR_INVALID_STATE` — implementation/routes/academic_blocks.py:54-58
- §3.3 — insert — `priority_score` computed and stored at block creation, recomputed in finalization pass 1 — implementation/routes/academic_blocks.py:77, implementation/services/placement.py:55-63
- §3.4 — insert — event creation with `X-User-ID` naming no registered organization → `ERR_NOT_FOUND` — implementation/routes/events.py:85-87
- §3.4 — insert — negative setup/teardown minutes → `ERR_INVALID_REQUEST` — implementation/routes/events.py:110-111
- §3.4 — insert — approval against a non-`ACTIVE` room → `ERR_ROOM_NOT_AVAILABLE` — implementation/routes/events.py:63-64
- §3.4 — insert — free-cancellation void applies only to a live `PROVISIONAL` invoice (a `PAID` one is untouched); cancellation-with-charges moves `PROVISIONAL`→`FINALIZED` while an already-`PAID` invoice keeps its status — implementation/routes/events.py:313-321, implementation/services/invoices.py:159-160
- §3.4 — insert — rebooking sets `approved_by_user_id` to the rebooking actor's `X-User-ID` (affects later waiver SoD) — implementation/routes/events.py:352
- §3.4 — insert — bump cascade cancels fulfilled orders too ("fulfilled ones included") — implementation/services/cascade.py:35-37
- §3.5 — insert — order creation against a non-`APPROVED`/`CONFIRMED` event → `ERR_INVALID_STATE`; service-window margin bounds inclusive — implementation/routes/service_orders.py:41-51
- §3.5 — insert — negative `unit_cost_cents` → `ERR_INVALID_REQUEST` — implementation/routes/service_orders.py:102-103
- §3.5 — insert — shift coverage judged at minute granularity on UTC time-of-day of the service window bounds — implementation/routes/service_orders.py:165-173
- §3.5 — insert — fulfillment before `service_end_at` → `ERR_INVALID_STATE` — implementation/routes/service_orders.py:202-206
- §3.5 — insert — crew non-positive capacity or shift end not later than start → `ERR_INVALID_REQUEST` — implementation/routes/service_crews.py:18-23
- §3.6 — insert — waiver against `VOIDED`/`REFUNDED` invoice → `ERR_INVALID_STATE` (distinct from payment's `ERR_OVERPAYMENT`) — implementation/routes/invoices.py:80-81
- §3.6 — insert — refunds only from `PAID`/`PARTIALLY_PAID`; other statuses → `ERR_INVALID_STATE` — implementation/routes/invoices.py:108-109
- §3.7 — revise — physical-key slot drawn from the namespace 1..(`key_count` + `keys_lost_total`) with retired slots never reused (not "between 1 and key_count") — implementation/routes/access_grants.py:75-92

**Deliberately not pinned** (PRD and impl consistently silent, or already pinned by §2.9's global tier rules): from-state `ERR_INVALID_STATE` cases already covered by tier 6 (reinstate, decline, unplace, grant return/mark-lost); absence of range checks on enrollment/room numeric fields (impl enforces none, PRD states none); grant creation having no event-state gate; app-level transport fallbacks (unknown route → 404 envelope). Endpoint set, roles, 201/200 codes, and all 31 error-to-HTTP-status mappings were verified to match §4/§5 exactly.
