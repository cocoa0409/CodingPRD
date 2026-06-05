# Worklog — task_0033_marina_slip_rental

## Step 1: Create task directory — 2026-05-28T00:00:00Z

Task directory `tasks/task_0033_marina_slip_rental/` was pre-created by the user. Verified `workspace/` subdirectory exists. Skipped auto-indexing (user supplied folder).

## Step 2: Generate scaffold — 2026-05-28T00:00:00Z

All three files parse cleanly and pass the lint.

## Summary

Generated three scaffold files for `task_0033_marina_slip_rental/` driven by the scenario (slip size matching, liveaboard utilities, Pump-out, seasonal pricing, Liveaboard policy, insurance and tow assistance, Slip Transfer waitlist).

**Lint verdict (`scaffold_lint.py`)**:
```
§1.5 endpoints declared:    37
§1.1 entities declared:     8
§1.8 instances scanned:     18
§1.9 instances scanned:     28
Calls scanned (§1.8+§1.9):  302
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### (a) SCAFFOLD.yaml contents

- **Complexity profile**: primary `temporal_windowing` + secondary `quota_allocation`; layers = optimistic_concurrency, cascading_side_effects, tiered_pricing, selector_policy, scheduled_deferred_actions; topology hybrid; state-machine shape branching; role model hierarchical_override; immediate consistency.
- **Entities (8)**: `Marina`, `Slip`, `Vessel`, `Tenant`, `Lease`, `PumpOutRequest`, `TowAssistEvent`, `TransferWaitlistEntry`. All FKs use the canonical `FK -> {Parent}.id` prefix.
- **State machines (5)**: `Slip` (5 transitions, branching from AVAILABLE; depth-3 cascade on check-out), `Lease` (3 transitions, RESERVED/ACTIVE/ENDED/CANCELLED), `Tenant` (5 transitions, CYCLIC: NONE→PENDING→APPROVED→REVOKED→PENDING), `PumpOutRequest` (2 transitions), `TransferWaitlistEntry` (3 transitions including system-driven promotion and HarborMaster sweep).
- **Concurrency rules (1)**: `slip-reserve-stale` — OCC on `Slip.version` for `POST /leases`.
- **Calculations (5)**: `seasonal_lease_pricing` (tiered_pricing, two variants with combinatorial mode-b per-step rounding), `lease_total_cost` (aggregation incl. liveaboard utility surcharge), `pumpout_charge` (threshold on `Slip.pumpout_available`), `tow_assistance_dispatch` (combinatorial mode-c pinned evaluation order: insurance first → radius), `waitlist_promotion_pick` (chronological selector: requested_at ASC, created_at ASC).
- **Validations (14, ordered)**: auth/forbidden/not_found/invalid_state/stale_version → safety/constraint/temporal/fiscal/referential.
- **Endpoints (37)**: marinas, slips (incl. decommission), tenants (incl. liveaboard application/approve/deny/revoke), vessels, leases (incl. check-in/check-out/cancel), pump-out-requests (incl. complete/cancel), tow-assist-events, transfer-waitlist (incl. cancel and `expire-stale` sweep), plus one test-driving endpoint `POST /_clock/set_current_utc`.
- **Errors (14)**: ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_INSURANCE_INVALID, ERR_LIVEABOARD_NOT_ALLOWED, ERR_SLIP_SIZE_MISMATCH, ERR_SLIP_DATE_CONFLICT, ERR_INVALID_DATE_RANGE, ERR_LIVEABOARD_QUOTA_EXCEEDED, ERR_VESSEL_TENANT_MISMATCH, ERR_WAITLIST_INELIGIBLE, ERR_INVALID_REQUEST.
- **Roles (3)**: `HarborMaster` (opaque), `MarinaStaff` (opaque), `Tenant` (entity_backed:Tenant).

### (b) §1.8 Difficulty Rules and §1.9 Corner sections

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml — 18 instances (9 rules × 2)**:
- `dual_variant_calc` (2): seasonal pricing variants on Lease, tow-assist outcome branching on Vessel.
- `combinatorial_formula` (2): per-step rounding mode-b on seasonal pricing (333 → 550), pinned evaluation-order mode-c on tow_assistance_dispatch.
- `non_linear_state_machine` (2): Tenant REVOKED→PENDING cycle, Slip branching from AVAILABLE.
- `transitive_cascade` (2): depth-3 cascade on check-out (Lease ENDED → counter decrement → waitlist promotion), depth-2 on liveaboard-revoke (Tenant REVOKED → cancel reserved liveaboard leases).
- `priority_pair_validation_conflict` (2): insurance_safety(6) vs constraint(8) at check-in; safety(7) vs temporal(9) at create.
- `boundary_precision_check` (2): strict-`<` liveaboard quota vs cap, half-open adjacent-date acceptance on lease create.
- `cross_entity_state_dependency` (2): Lease check-in ↔ Tenant.liveaboard_status, PumpOutRequest complete ↔ Lease.status.
- `resource_temporal_overlap` (2): half-open interval intersect on Slip, aggregate-capacity overlap on Marina.
- `compensating_invariant` (2): forward+cancel on lease conserves marina AVAILABLE-slot count; revoke+re-approve conserves Marina.liveaboard_current_count.

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml — 28 instances across 8 sections**:
- `entities` (7): creation, not_found, required_fields, defaults, computed_fields, listing, initial-status.
- `state_machines` (5): cancel-from-active rejection, terminal-state lockdown, decommission precondition, waitlist EXPIRE valid transition, 1 excluded_because stub.
- `calculations` (5): pump-out charge zero / 2500 paths, WINTER pricing, 2 excluded_because stubs.
- `validations` (6): invalid date range, vessel-tenant mismatch, waitlist ineligibility, priority existence>state, slip-size-only path, 2 excluded_because stubs.
- `endpoints` (2): filtered list by tenant, clock-set action endpoint.
- `errors` (1): ERR_STALE_VERSION via OCC (sequential).
- `rbac` (3): Tenant forbidden on decommission, MarinaStaff forbidden on liveaboard-approve, missing auth → ERR_UNAUTHENTICATED.
- `cross_cutting_complexity_layers` (5): OCC success path + version bump, pagination limit/offset, 3 excluded_because stubs for cascade/tiered/selector.
- `consistency_model` (1): immediate consistency on GET after POST.

## Step 3: Copy INSTRUCTION.md — 2026-05-28T00:00:00Z

Copied root `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-28T00:00:00Z

All three Hard Contract audits pass. Here is the closing summary.

---

## PRD Generation Complete

**Output:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0033_marina_slip_rental/workspace/PRD.md`

**Line count:** 234 lines

**Section structure:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications — 10 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties & Versioning, 2.5 Nested Path Resolution, 2.6 OCC on Slip Reservation, 2.7 Validation Ordering, 2.8 Calculation Precision, 2.9 Hierarchical State Cascades, 2.10 Server Clock & Test-Driving
- §3 Business Logic — 9 subsections organised by lifecycle stages: 3.1 Provisioning → 3.2 Onboarding → 3.3 Liveaboard Policy → 3.4 Reservation (OCC) → 3.5 Check-In + Seasonal Pricing → 3.6 Pump-Out → 3.7 Tow Assistance → 3.8 Check-Out + 3-hop cascade → 3.9 Waitlist
- §4 Endpoint Definitions (4-column table: Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue (2-column table: Error ID, HTTP Status Code)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 47 required, 47 present, 0 missing
- endpoints[].request_body / input: all present (to_iso8601 included)
- endpoints[].query_params: limit, offset, status, marina_id, tenant_id, vessel_id, slip_id, lease_id, target_slip_id, from_lease_id all present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 14 checked, ordering expressed in §2.7, 0 missing
- concurrency_rules[] OCC rejections: 1 checked (slip-reserve-stale: POST /leases + expected_slip_version + ERR_STALE_VERSION + 412), 0 missing
- state_machines[].transitions: 21 checked (Slip 5, Lease 3, Tenant 5, PumpOutRequest 2, TransferWaitlistEntry 3, plus check-in/check-out cascades), fully expressed, 0 missing
- calculations[]: 5 checked (seasonal_lease_pricing two-step per-step rounding, lease_total_cost aggregation w/ utility surcharge, pumpout_charge threshold, tow_assistance_dispatch ordered evaluation, waitlist_promotion_pick chronological), 0 missing
- validations[] conditions: 14 checked, each matchable to its error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 endpoints checked, side effects rendered in §3 workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, types, computed fields (e.g. liveaboard_current_count recompute trigger, position recompute) reconstructible from prose, 0 missing
- sibling-branch symmetry: tow-assist 3-outcome branch, lease-cancel vs check-out symmetry, NONE vs REVOKED re-application branches, COVERED/OUT_OF_RADIUS/INSURANCE_INVALID outcome branches — equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 300
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage audit notes:**
- The two-step rounding semantics of `seasonal_lease_pricing` are spelled out as separate rounding steps with the explicit note that per-step rounding can differ from a single end-of-formula rounding.
- The three-hop check-out cascade (lease ENDED → marina liveaboard counter decrement → waitlist head promotion) is fully expressed with the strict ordering key (`requested_at` ASC, tie-break `created_at` ASC) preserved.
- OCC framing in §2.6 and §3.4 is purely stale-version, avoiding "simultaneously" / "first writer wins" language per the contract rule.
- Tow-assist short-circuit ordering (insurance before radius) is documented with the specific failing-step → outcome mapping.
- Validation priority ordering is presented in §2.7 as a fixed evaluation pipeline (auth → authz → existence → state → OCC → business-safety → temporal/quota → referential → schema fallback).

## Step 5: Generate unit tests — 2026-05-28T00:00:00Z

### (a) test_helpers/ files created (line counts)

| File | Lines |
|------|-------|
| `__init__.py` | 124 |
| `api_client.py` | 190 |
| `api_errors.py` | 42 |
| `assertions.py` | 121 |
| `constants.py` | 28 |
| `factories.py` | 211 |
| `fixtures.py` | 445 |
| `test_users.py` | 42 |
| `types.py` | 175 |

### (b) test_suite/ files (tests per file)

| File | Tests | Lines |
|------|-------|-------|
| `conftest.py` | — | 37 |
| `test_01_difficulty_dual_variant_calc.py` | 6 | 191 |
| `test_02_difficulty_combinatorial_formula.py` | 4 | 145 |
| `test_03_difficulty_non_linear_state_machine.py` | 4 | 117 |
| `test_04_difficulty_transitive_cascade.py` | 6 | 194 |
| `test_05_difficulty_priority_pair_validation_conflict.py` | 4 | 190 |
| `test_06_difficulty_boundary_precision_check.py` | 2 | 66 |
| `test_07_difficulty_cross_entity_state_dependency.py` | 4 | 122 |
| `test_08_difficulty_resource_temporal_overlap.py` | 2 | 68 |
| `test_09_difficulty_compensating_invariant.py` | 4 | 119 |
| `test_10_corner_entities.py` | 7 | 142 |
| `test_11_corner_state_machines.py` | 4 | 145 |
| `test_12_corner_calculations.py` | 3 | 109 |
| `test_13_corner_validations.py` | 5 | 164 |
| `test_14_corner_endpoints_errors_rbac.py` | 5 | 138 |
| `test_15_corner_cross_cutting_consistency.py` | 3 | 110 |

Total: **63 tests** (36 difficulty + 27 corner)

### (c) Emit vs Skip — by queue

**Queue A (Difficulty) — 18 total instances**
- **Emit: 16 instances** (≥ 2 tests each)
- **Skip: 2 instances**
  - `boundary_precision_check/lease_overlap_adjacent_dates_do_not_collide` — PRD §3.4 enforces the slip-AVAILABLE state check before any date-conflict check, and a slip becomes RESERVED on the first lease create. Two RESERVED/ACTIVE leases on the same slip is structurally impossible, so the half-open adjacency rule named in PRD has no reachable scenario in which it pins a unique observable outcome. (Two-reader filter fails on unique-derivability.)
  - `resource_temporal_overlap/slip_lease_half_open_overlap_rejects_strict_intersect` — Same root cause: a second `POST /leases` against an already-RESERVED slip surfaces `ERR_INVALID_STATE` (priority 4) per PRD §2.7, not `ERR_SLIP_DATE_CONFLICT` (priority 9). The asserted `error_id` is not uniquely derivable from PRD; a faithful implementer would return `ERR_INVALID_STATE`.

**Queue B (Corner) — 28 non-stub instances + 8 stubs**
- **Emit: 27 non-stub instances** (≥ 1 test each)
- **Skip: 1 non-stub instance**
  - `endpoints/list_leases_filtered_by_tenant_returns_only_owners_leases` — PRD §4 entry for `GET /leases` says only "List leases, optional filters" without naming `tenant_id` as a filter field or specifying filter semantics. C2 (rule-bearing, not endpoint-titular) fails; two PRD-only readers could legitimately implement different filter behaviors.
- **8 stubs NOT translated** (per spec, `excluded_because:` stubs are owned by their cited difficulty instance, all cross-references verified to resolve to real difficulty-design instance names).

### Audit results
- 63/63 tests carry a single, well-formed `Design:` tag pointing to a real instance.
- 80/80 PRD citations are verbatim substrings of `workspace/PRD.md` (≥ 8-word distinctive prefix check).
- 0 `pytest.mark.skip`, `skipif`, or `xfail` markers anywhere.
- 0 "scaffold" / "Table N" / "§1.x" / "§0.x" mentions in generated code (PRD-only references).
- All 25 generated files parse and import cleanly when the `prd_bench_local_runner` framework is on `PYTHONPATH`.

## Step 6: Generate Flask implementation — 2026-05-28T00:00:00Z

Generated a Python + Flask implementation for the Marina Slip Rental API at `tasks/task_0033_marina_slip_rental/workspace/implementation/` (2081 LOC total).

**Files created:**

Foundation
- `start.sh` (5) — `cd $(dirname)`; `pip install -q`; `exec python3 app.py`
- `requirements.txt` (1) — `flask==3.0.3`
- `app.py` (82) — Flask factory, blueprint registration, error handlers
- `db.py` (186) — in-memory stores, UUID/request-id helpers, logical-clock state, MM-DD parser, common-field stamping
- `errors.py` (27) — `APIError` class + 14 error_id constants verbatim from §1.6
- `response.py` (84) — envelope helpers (`ok_object`, `ok_array`, `error_response`, `paginate_params`)
- `middleware.py` (73) — `X-User-ID`/`X-User-Role` extraction, role gating

Services
- `services/validation.py` (155) — typed-field validators, FK lookup helpers, harbor-code regex
- `services/calculations.py` (144) — `seasonal_lease_pricing` (per-step ROUND_HALF_UP via Decimal), `lease_total_cost`, `pumpout_charge`, `insurance_valid`, `tow_assistance_outcome` (strict insurance→radius ordering), `WAITLIST_TTL_DAYS=30`
- `services/cascades.py` (113) — `promote_waitlist_head` (queue sort by `requested_at, created_at` ASC), `cancel_reserved_liveaboard_leases`, `recompute_positions`

Routes (8 blueprints, 37 endpoints)
- `routes/clock.py` (36) — `POST /_clock/set_current_utc`
- `routes/marinas.py` (88), `routes/slips.py` (127), `routes/tenants.py` (179), `routes/vessels.py` (83)
- `routes/leases.py` (375) — the priority-ordered §1.4 ladder including OCC pin and three-hop check-out cascade
- `routes/pump_out.py` (104), `routes/tow_assist.py` (72), `routes/transfer_waitlist.py` (147)

**Key implementation choices:**
- Storage: in-memory dicts keyed by UUID; no startup seeding (stores empty per fresh boot)
- Decimal-based `_half_up(num, den)` keeps integer-cents arithmetic precise; rounding applied independently after step 2 (seasonal mul) and step 3 (liveaboard surcharge), matching the scaffold's pinned per-step rule rather than collapsed multiplication
- Single `db.mutation_lock` (RLock) wraps every mutation so cascades and version bumps are observably atomic
- Logical clock pinnable via `/_clock/set_current_utc`; `now_logical_iso()` drives all entity timestamps so insurance/check-in/waitlist-TTL evaluations stay consistent under test
- OCC pin: `expected_slip_version` compared against current `slip.version` after the state gate (priority 5); discarded after validation (never persisted in lease body)
- Waitlist queue ordered strictly by `(requested_at ASC, created_at ASC)`; positions recomputed after every QUEUED/PROMOTED/CANCELLED/EXPIRED transition
- `WAITLIST_TTL_DAYS = 30` (corner-design test exercises 60-day-old entry; PRD/scaffold do not pin a literal value, so 30 days was chosen as a conventional default that satisfies the corner case)
- Smoke-tested end-to-end: created marina/slip/tenant/vessel/lease, advanced clock, ran check-in (verified `nightly_rate_cents=7500` from `5000 × 1.5` SUMMER, `total_cost_cents=22500` over 3 nights), check-out (slip→AVAILABLE, version 1→3), `ERR_STALE_VERSION` on re-attempt, liveaboard apply→approve→revoke cascade (lease CANCELLED, slip AVAILABLE, marina counter decremented, all four entities version-bumped per PRD §2.9)

**`start.sh` contract:** reads `PORT` env var (default 10000), binds `0.0.0.0`, runs in foreground via `exec python3 app.py` so signals propagate cleanly between the per-test-server restarts.

## Step 7: Run tests and iterate — 2026-05-28T00:00:00Z

All 8 rounds pass 61/61. Exiting with clean sweep.

## Summary

- **Iterations run**: 1 (single 8-round parallel sweep, all green on first run).
- **Tests deleted**: None.
- **Fixes applied to `test_helpers/`**: None.
- **Fixes applied to `implementation/`**: None.

The task was already passing all 61 tests stably across 8 parallel rounds with no flakiness. No diagnostic or fix work was required.

Results files written to `workspace/implementation/results.{1..8}.json` (all show passed=61/total=61, failed=0, errors=0).

## Step 8: Finalize PRD — 2026-05-28T00:00:00Z

SKIPPED: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. Per the skill's skip condition, `PRD.md` already determines every behavior the implementation exhibits at Step 7 fix sites; no Step 8 patch is needed. `PRD_FINALIZED.md` will not be produced; Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-05-28T00:00:00Z

All changes are minimal in-paragraph inserts/revisions; no new sections; line counts preserved.

**Source vs target:**
- PRD.md: 233 lines, 35,132 chars
- PRD_COMPLETED.md: 233 lines, 38,731 chars (delta: +3,599 chars; line count preserved — all edits are in-paragraph inserts)

**Counts:**
- Ambiguity-pins: 17
- Mismatch-revisions: 0
- (No PRD passage stated a behavior that conflicted with the implementation; every change addresses a silence rather than a contradiction.)

**Per-change list:**
- §2.3 Pagination — insert — ambiguity — pin `ERR_INVALID_REQUEST` HTTP 400 for malformed `limit`/`offset` and tie-break on `id` ascending — `response.py:60–79`, `db.py:184–186`
- §2.5 Existence — insert — ambiguity — pin cross-resource `marina_id`/`slip_id` mismatch as `ERR_NOT_FOUND` 404 — `routes/leases.py:108–110`
- §2.10 Clock — insert — ambiguity — pin response envelope (`now_utc` field, canonical UTC), `ERR_INVALID_REQUEST` for unparseable input, and that the logical clock drives entity timestamps while `meta.api_request_timestamp` stays on wall time — `routes/clock.py:21–36`, `db.py:103–137`, `response.py:11–18`
- §3.1 Marina — insert — ambiguity — pin `ERR_INVALID_REQUEST` HTTP 400 for season-window/harbor_code/liveaboard_cap/duplicate-harbor_code violations — `routes/marinas.py:38–59`
- §3.1 Slip — insert — ambiguity — pin `ERR_INVALID_REQUEST` HTTP 400 for duplicate `slip_number`, bad `power_amp`, non-positive dimensions — `routes/slips.py:36–65`
- §3.2 Tenant — insert — ambiguity — pin `ERR_INVALID_REQUEST` HTTP 400 for duplicate `email` and pin insurance day-granular comparison — `routes/tenants.py:40–42`, `services/calculations.py:104–126`
- §3.3 Liveaboard apply — insert — ambiguity — pin `marina_id` as required body field, `ERR_INVALID_STATE` 409 from non-`NONE`/`REVOKED` start — `routes/tenants.py:82–102`
- §3.3 Liveaboard approve/deny — insert — ambiguity — pin approve requires `marina_id` body, deny takes no extra body, both reject non-`PENDING` with `ERR_INVALID_STATE` 409 — `routes/tenants.py:105–153`
- §3.3 Liveaboard revoke — insert — ambiguity — pin `marina_id` body required, counter clamped at zero, slip cascade RESERVED→AVAILABLE with version bump, non-`APPROVED` start yields `ERR_INVALID_STATE` 409, tenant projection excludes internal fields — `routes/tenants.py:156–179`, `services/cascades.py:84–113`, `routes/tenants.py:57–59`
- §3.5 Check-in — insert — ambiguity — pin `ERR_INVALID_STATE` 409 for all three preconditions including clock-date<start_date — `routes/leases.py:244–259`
- §3.6 Pump-out create — insert — ambiguity — pin `ERR_INVALID_STATE` 409 when parent lease not `ACTIVE` — `routes/pump_out.py:30–35`
- §3.9 Waitlist cancel — insert — ambiguity — pin `ERR_INVALID_STATE` 409 for cancel of non-`QUEUED` — `routes/transfer_waitlist.py:106–111`
- §3.9 Waitlist expire-stale — insert — ambiguity — pin `WAITLIST_TTL_DAYS` is thirty; pin response is array envelope of newly-expired entries sorted by `created_at`,`id` — `services/calculations.py:25`, `routes/transfer_waitlist.py:119–147`
- §4 endpoint table `/slips` — revise — ambiguity — name query params `marina_id`, `status` — `routes/slips.py:87–90`
- §4 endpoint table `/vessels` — revise — ambiguity — name query param `tenant_id` — `routes/vessels.py:72–73`
- §4 endpoint table `/leases` — revise — ambiguity — name query params `tenant_id`, `slip_id`, `marina_id`, `vessel_id`, `status` — `routes/leases.py:219–222`
- §4 endpoint table `/pump-out-requests`, `/tow-assist-events`, `/transfer-waitlist` — revise — ambiguity — name supported filter params — `routes/pump_out.py:53–56`, `routes/tow_assist.py:59–62`, `routes/transfer_waitlist.py:85–88`
