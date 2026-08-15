# Worklog — task_1327_stevedoring_longshore_labor_ordering

## Step 1: Create Task Directory — 2026-08-12T22:08:00.000Z

Pre-assigned by pipeline launcher; `tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/` verified to exist. Skipped index scan per instructions.

## Step 2: Generate Scaffold — 2026-08-12T23:03:30.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/SCAFFOLD_CORNER_DESIGN.yaml`

## §1.1–§1.7 counts (SCAFFOLD.yaml)
- **12 entities**: VesselCall, ShiftWindow, GangOrder, Worker, DispatchAssignment, EquipmentUnit, EquipmentAssignment, MoveRecord, DamageClaim, SafetyIncident, TimesheetEntry, Invoice
- **11 state machines** (58 transitions), including cycles: GangOrder WORKING↔SUSPENDED, TimesheetEntry SUBMITTED→REJECTED→SUBMITTED, Invoice ISSUED→DISPUTED→FINALIZED→ISSUED, plus MANNED→DISPATCHING regressions
- **4 OCC concurrency rules** (dispatch-batch, gang amend, worker status, invoice adjust — all true create-with-supersede races, all 412)
- **11 calculations** (seniority rank, dispatch selector, filled-headcount derivation, MPH, bonus pool, payroll OT/DT/meal, posture derivation, damage liability, equipment replacement selector, buffered-window conflict, invoice tiered pricing)
- **11 validation priorities** (auth → fiscal), **66 endpoints**, **27 errors**, **7 roles** (GangForeman is `entity_backed:Worker`; rest opaque; segregation-of-duties on claims decide and timesheet approve)

## §1.8 difficulty design — 22 instances (≥2 per rule)
dual_variant_calc 2 (invoice provisional 2,870,900¢ vs final 2,962,100¢; claim 5,000,000¢ vs 5,950,000¢) · combinatorial_formula 3 covering all three modes: (a) payroll NIGHT+OT+meal-penalty = 46,200¢, (b) manhour line rounded once = 20,583¢ vs forbidden 20,584¢, (c) discount tier keyed on pre-discount subtotal exactly 3,000,000¢ → 150,000¢ · non_linear_state_machine 2 · transitive_cascade 2 (safety depth-4: incident→posture→suspend→release→unit-free; suspension-bump-redispatch depth-3) · priority_pair_validation_conflict 3 (state>safety, safety>temporal, schema>state) · boundary_precision_check 3 (OT at 480/481; MPH exactly 25.0; check-in at filled==required) · cross_entity_state_dependency 3 · resource_temporal_overlap 2 (worker half-open adjacency vs equipment 30-min buffer) · compensating_invariant 2 (filled_headcount bump+refill; vessel actual_moves record+void)

## §1.9 corner design — 50 active instances + 10 `excluded_because` stubs
entities 7, state_machines 7+2 stubs, calculations 10+4 stubs, validations 12+4 stubs, endpoints 2, rbac 4, cross_cutting 7 (5 OCC + selector retry exclusion + amendment bump waterfall), consistency_model 1. All 27 error codes are triggered by at least one instance.

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(66 endpoints, 12 entities, 22+50 instances, 844 calls scanned)

## Notable design decisions
- **Flat topology** (all resources top-level under `/api/`, FKs in bodies, filtered-list GETs for reverse reachability) and **segregation-of-duties** role model — both diversity-prioritized per §0.3.
- **No logical clock**: seniority (registered_on + created_at tie-break), payroll, and stoppage are all data-driven, so no `/_clock` endpoint was needed; every rule is deterministic from request payloads alone.
- **ERR_GANG_FULL reachability fix**: open-slots accounting (`required − filled − offered`) makes over-offer impossible, so the full-gang boundary is reached via headcount amendment shrinking `required` to `filled` while an OFFER survives (amendments never cancel outstanding offers — pinned).
- **Equipment multi-booking**: units accept multiple disjoint bookings while ASSIGNED (ERR_EQUIPMENT_UNAVAILABLE only when DOWN) — otherwise the 30-minute buffered-window rule would be unreachable behind the availability check.
- **OCC freshness**: equipment bookings and check-ins mutate GangOrder (derived-field recompute bumps `version`), so affected recipes re-capture the version via GET immediately before OCC writes — no bare-literal versions anywhere (lint rule (e) clean).
- **Suspension releases equipment** and resume requires re-acquisition (ERR_NO_EQUIPMENT_ASSIGNED until then) — the WORKING→SUSPENDED→WORKING cycle is adversarially non-free; incident clear deliberately does NOT auto-resume.

## Step 3: Copy Shared Files — 2026-08-12T23:04:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T23:20:00.000Z

All three hard contracts pass. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/PRD.md`.

**Section structure** (324 lines):
- §1 Introduction — 2 paragraphs (business pain-point angle, then system scope with `/api` mount and the two structural commitments)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (7 roles with identity translations: `GangForeman` entity-backed by `Worker`, six opaque), 2.2 Response Structure (verbatim fixed block, `req_RANDOMALPHANUM123456` / empty `data` preserved byte-for-byte), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ASC, batch creation-sequence tie-break, all 9 filter param names), 2.4 Common Properties + flat topology, 2.5 Validation Order (all 11 priority tiers in explicit prose with a worked example), 2.6 OCC (4 endpoints, 3 version fields, exact error IDs, no race framing), 2.7 Money/Rounding (integer cents, round-half-up, per-line-vs-single-end pinning), 2.8 Half-Open Intervals + 30-min buffer + 960-minute cap, 2.9 Derived Fields & Automatic Transitions, 2.10 Safety Posture Gates
- §3 Business Logic — 9 subsections organized along the operational timeline (vessels/shifts → gang orders → dispatch → equipment → work execution/MPH bonus → safety cascades → damage claims → timesheets/payroll → invoicing)
- §4 Endpoint table — 66 rows, 4 columns only; §5 Error catalogue — 27 rows, 2 columns only

**Coverage of scaffold rules (§1.1–§1.7):**
- §1.1 entities: all 12 entities, all fields rendered (102/102 required identifiers present in backticks — entity fields, request inputs, query params, plus productivity-read output fields)
- §1.2 state machines: all 10 machines rendered with every transition's from/to states, preconditions paired with error IDs, and all side effects (including sibling symmetry: cancel from pre-WORKING vs WORKING, ACCEPTED vs DENIED decide, OFFERED vs CHECKED_IN bump, DRAFT vs DISPUTED adjustment)
- §1.2.1 concurrency: all 4 OCC rules with endpoint + `expected_<parent>_version` + exact error ID + 412
- §1.3 calculations: all 11 rendered as precise prose (seniority rank, dispatch selection with forced-list semantics and `ERR_WORKER_DOUBLE_BOOKED` carve-out, manning derivation, MPH with zero/negative productive-minutes guard, bonus with at-threshold variant, payroll with 480/720/300 boundary rules, posture derivation, damage liability with pinned percentage→cap→deductible order, equipment replacement ranking, 30-minute buffer with exactly-30-minute-gap-allowed, invoice tiered pricing with pinned per-line rounding and pre-discount subtotal discount tiers)
- §1.4 validations: all 11 priorities with explicit "first failure wins" ordering
- §1.5 endpoints: all 66 in the table
- §1.6 errors: all 27 in the catalogue and each mentioned in §2/§3 prose
- §1.7 roles: all 7 with exact spelling

**Hard contract reports:**
- Field coverage: 102 required, 102 present, 0 missing — PASS
- Rule coverage: validations priority 11/11, OCC 4/4, transitions 47/47, calculations 11/11, validation conditions matchable to error IDs, endpoint side effects expressed, structured field content (defaults/initials) reconstructible, sibling branches symmetric — PASS
- §3 path purity: 550 backtick tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path combos — PASS

**Zero-Silence notes (judgment calls where the scaffold was implicit):**
1. Gang-order amendment outside `PLACED`/`DISPATCHING`/`SHORT_MANNED`/`MANNED` and move-record creation outside `WORKING`/`SUSPENDED` and invoice creation while the vessel is `SCHEDULED` were bound to `ERR_INVALID_STATE` (the generic state-precondition error per validation tier 6) — the scaffold named the state sets but not the error binding.
2. "Exactly one non-VOIDED invoice per vessel call" was rendered as "exactly one invoice per vessel call" since no `VOIDED` invoice status exists in the state machine; no error ID was invented for the second-create rejection.
3. Check-in re-evaluating the double-booking rule was stated explicitly (validation tier 9's `applies_to` includes check-in even though the assignment state machine doesn't list it as a check-in precondition).

## Step 5: Generate Unit Tests — 2026-08-13T00:05:00.000Z

Done. Full test infrastructure generated for task_1327.

## Files written

**`test_helpers/`** (9 modules):
- `types.py` — 18 enums + 12 entity TypedDicts (all entities carry common fields per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 62 methods, one per PRD §4 endpoint
- `api_errors.py` — all 27 error IDs + HTTP status map registered with the framework
- `assertions.py` — per-entity shape assertions + approved-timesheet breakdown invariant + invoice total/balance invariants
- `factories.py` — payload factories with auto-uniquified registration numbers / voyage numbers / unit codes
- `constants.py` — payroll breakpoints (480/720/300), period multipliers, container tiers, equipment rates, damage cap/deductible, discount tiers, 30-min buffer, 960-min shift cap
- `test_users.py` — `TEST_USERS` for all 7 roles + `make_foreman_headers(worker_id)` (mandatory for the entity-backed GangForeman role) + adjuster/payroll builders for segregation tests
- `fixtures.py` — 5-tier composite helpers: atomic builders, `setup_vessel_with_open_shift` → `setup_placed_gang` → `setup_dispatched_gang` → `setup_working_gang` → `setup_completed_gang` → `setup_completed_vessel` → `setup_finalized_invoice`/`setup_issued_invoice`; OCC-safe `dispatch_batch`/`amend_gang`/`adjust_invoice` that re-read parent versions
- `__init__.py` — barrel export

**`test_suite/`** — `conftest.py` + 9 test files, **94 tests, all collected by pytest cleanly**.

## Test counts
- **Queue A (Difficulty): 44 tests** — all 22 instances × 2 tests each
- **Queue B (Corner): 50 tests** — all 50 non-stub instances × 1 test each
- 10 `excluded_because:` stubs not translated; all their `difficulty_instance` cross-references verified to resolve

## Skipped instances
None. Every non-stub instance passed the PRD-first two-condition filter. Notably, the three `priority_pair_validation_conflict` instances were **kept** (not skipped under the validation-priority silence pattern) because PRD §2.5 explicitly states the fixed priority order ("the first failing check wins") and §2.10 pins the stoppage gates at tier 7 — the ordering is verbatim-covered and uniquely derivable. Two corner asserts were narrowed where the PRD leaves a design space open: absolute `version == 1` at creation (PRD pins only "increments with every modification", so all OCC tests assert relative version arithmetic instead), and "status remains PLACED after amendment" (PRD's manning-derivation prose is ambiguous for a pre-dispatch amendment).

## Stage 2 self-check (tag audit)
- Every test has exactly one `Design:` docstring line; all 94 tags resolve to real instances; no stub tags, no dual tags, no untagged tests
- Coverage: 22/22 difficulty instances at ≥2 tests, 50/50 corner instances at ≥1 test — zero shortfalls
- All 148 PRD citations verified verbatim against PRD.md (whitespace-normalized grep); 6 ellipsis-fused / table-row citations were found and fixed
- No `skip`/`skipif`/`xfail` markers; no scaffold references in comments or docstrings; all modules compile and import under the framework's PYTHONPATH

## Step 6: Generate Implementation — 2026-08-13T00:05:30.000Z

The implementation is complete and verified. Summary:

## Files written (17 files, all under `tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/implementation/`)

- `start.sh` — guarded launcher (`exec python3 app.py`, pip install only when flask missing), `requirements.txt`
- `app.py` — Flask entry, error handlers, per-request global lock (deterministic OCC under concurrency), auth before_request; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (12 entity dicts, empty at boot, no seeding), UUID ids, 3-fractional-digit ISO8601 UTC timestamps, monotonic creation sequence for list tie-breaking
- `errors.py` — full 27-error catalog with exact IDs/HTTP statuses
- `response.py` — envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp`, `response_type`, `data`; pagination fields `limit/offset/total_count/has_more` in meta
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (7 declared roles), RBAC, schema validators, OCC version helper, pagination (default 10, 1–100, offset ≥ 0)
- `services.py` — all derived-field recomputes, cascades, and calculations
- `routes/` — 11 modules (vessels, shifts, gangs, workers, assignments, equipment, moves, claims, safety, timesheets, invoices)

**Endpoint count: 66**, all wired with per-endpoint role sets from PRD §4 (including the restricted GET lists, e.g. invoices GET limited to Admin/Superintendent/BillingClerk).

**State machines implemented (11 + worker status):** VesselCall (incl. auto BERTHED→WORKING on first shift start), ShiftWindow (incl. bubble-up close when all gangs terminal), GangOrder (full cyclic machine: PLACED/DISPATCHING/MANNED/SHORT_MANNED/WORKING/SUSPENDED with regressions), DispatchAssignment (incl. no-show/bump auto-offer and amendment bump waterfall by `seniority_rank_at_dispatch` DESC, `created_at` DESC), EquipmentUnit, EquipmentAssignment (breakdown → replacement selection by least-utilization/created_at), MoveRecord, DamageClaim (provisional 50% → cap/deductible final), SafetyIncident (work_posture derivation + FULL_STOPPAGE cascade releasing equipment and incrementing `suspension_count`), TimesheetEntry (SUBMITTED↔REJECTED cycle, segregation-of-duties on approve), Invoice (DRAFT→FINALIZED→ISSUED→DISPUTED loop, per-line round-half-up-then-sum, tiered discount on pre-discount subtotal).

**Verification:** two hand-built smoke suites (happy-path E2E with cent-exact invoice/payroll/bonus assertions; edge suite covering SHORT_MANNED exhaustion, OCC 412s, double-booking half-open adjacency, GANG_FULL, suspension cascade, dispute cycle, credit limit 402, payroll boundaries at 300/480/720) — both pass, each against a fresh `start.sh` boot; store confirmed empty on every boot.

**Design decisions where the PRD was ambiguous:**
1. `assigned_equipment_ok` at gang create: applied the derivation (`true` iff `required_equipment_count == 0`) rather than the "born false" prose, so zero-equipment gangs can start work (the "true exactly when coverage ≥ required" biconditional judged more specific).
2. Second invoice for a vessel call → `ERR_INVALID_STATE` 409 (catalog has no duplicate-invoice ID; uniqueness tier is 409-family).
3. Missing `expected_*_version` → `ERR_VALIDATION` 400 (schema tier 4 precedes concurrency tier 5; PRD says the field is "non-optional").
4. Duplicate `unit_code` → `ERR_VALIDATION` 400 (no dedicated error ID exists; `ERR_DUPLICATE_REGISTRATION` is worker-specific).
5. Invoice create allowed for BERTHED/WORKING/COMPLETED, rejected for SCHEDULED and CANCELLED ("BERTHED or later").
6. Worker → INACTIVE performs no cascade and has no checked-in/working precondition (spec defines those only for SUSPENDED).
7. Manning derivation never moves a PLACED order (only DISPATCHING/SHORT_MANNED/MANNED); dispatch batch bumps version exactly once per spec even when the pool is exhausted.
8. Forced `worker_ids`: `ERR_WORKER_DOUBLE_BOOKED` (tier 9) wins over `ERR_WORKER_INELIGIBLE` (tier 10) when any listed worker fails only the overlap clause; unknown forced IDs → 404 (body FK existence, tier 3).
9. Provisional invoice manhour line sums `required_headcount × 480` over non-CANCELLED gang orders.

## Step 7: Run Tests and Iterate — 2026-08-13T00:40:00.000Z

All 8 rounds pass: 94/94 tests across every round.

---

## Summary

**Iterations run:** 2 (one initial sweep to surface failures, one post-fix sweep confirming clean pass).

**Tests deleted:** None. Both failing tests trace verbatim to PRD §3.2 ("Every accepted amendment increments the order's `version` by one.") and §2.2/§2.4 — unique derivability held, so they stayed.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**

- `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/implementation/services.py` — `recompute_manning(gang)` and `recompute_equipment_ok(gang)`: added a `_touch=True` keyword parameter so callers that already own the version bump can suppress the inner `touch(gang)`. The functions still update `filled_headcount` / `offered_count` / `status` / `assigned_equipment_ok` identically; only the version-increment side effect is now opt-out.

- `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/implementation/routes/gangs.py` — `amend_gang`: previously called `touch(gang)` for the amendment itself, then invoked `services.recompute_equipment_ok(gang)` and `services.recompute_manning(gang)` unconditionally — each of which could fire a second `touch(gang)`. With `required_equipment_count=0` (the factory default), `recompute_equipment_ok` flipped the birth-default `assigned_equipment_ok=False` to `True` (0 bookings ≥ 0 required) and bumped the version again, producing `version=3` after a single accepted amendment and violating PRD §3.2's "increments the order's `version` by one." Rewrote the amend path so the recomputes run with `_touch=False` and the explicit `touch(gang)` at the end is the single version bump for the whole mutation.

**Verification:** 8 parallel rounds × 94 tests each — all passed, no flakiness observed.

## Step 8: Finalize PRD — 2026-08-13T01:00:00.000Z

Both edits applied cleanly, confined to §3.2's amendment paragraph (line 140). Final verification complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 323 lines, PRD_FINALIZED.md = 323 lines — 0.0% line delta (both edits are inline sentence revisions inside the single §3.2 amendment paragraph; one paragraph touched, no sections added).

**Changes (both in §3.2, both trace to the two `<step_7_diff>` implementation fixes):**

- §3.2 — revise — "Every accepted amendment increments the order's `version` by one" → "…by exactly one in total: the field updates and every derived-field recompute the amendment triggers — the manning and equipment-coverage recomputes described below — constitute a single mutation on the order, so none of those recomputes adds a version increment of its own." Pins the behavioral content of the `_touch=False` suppression and the single terminal `touch(gang)`. — `implementation/routes/gangs.py:106,122-124`; `implementation/services.py:124,160` (`_touch` parameters).
- §3.2 — insert — after the manning-recompute sentence, added: equipment coverage is re-evaluated within the same mutation on every accepted amendment against the possibly amended `required_equipment_count`, even when no equipment assignment changed, so a zero-equipment-requirement order flips `assigned_equipment_ok` from birth `false` to `true` at its first accepted amendment. PRD.md was genuinely silent here: §2.9 lists the recompute trigger as "every equipment-assignment change" (an amendment is not one) and §3.2 mentioned only manning recompute, while §3.4's "true exactly when" biconditional cannot be read as a standing invariant (§3.2's birth-`false` rule falsifies it at creation). — `implementation/routes/gangs.py:122`; flip semantics at `implementation/services.py:160-171`.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**

- Edit 1 (version accounting):
  - (a) Subject: gang-order `version` increment accounting when one request triggers derived-field recomputes.
  - (b) Paths enumerated and read: `routes/gangs.py:90-125` (amend), `128-147` (cancel — explicit `touch` plus recomputes with default `_touch=True`, so cancel can multi-bump), `150-183` (start-work), `186-208` (complete), `211-254` (dispatch-batch, single bump per §3.3); `services.py:124-144` (`recompute_manning`), `160-171` (`recompute_equipment_ok`), `211-219` (`suspend_gang`), `357-360` (`auto_offer`); `routes/equipment.py:114,173,186`; `routes/assignments.py:81,86,100`; `routes/workers.py:96`; `db.py:65-68` (`touch`).
  - (c) Adjustment: deliberately scoped the "exactly one in total" claim to *accepted amendments* rather than writing a universal "one request = one bump" rule, because `cancel_gang` (gangs.py:143-145) legitimately bumps the order's version up to three times via unsuppressed recomputes; also kept the claim on *the order's* version only, since waterfall-bumped assignments each get their own `touch` (gangs.py:117).
- Edit 2 (amend-time `assigned_equipment_ok` recompute):
  - (a) Subject: `assigned_equipment_ok` recompute triggers and its value lifecycle (birth `false` vs. §3.4 derivation).
  - (b) Paths enumerated and read: `routes/gangs.py:51-55` (create — born `false`, no recompute), `122` (amend — unconditional recompute), `144` (cancel), `169-171` (start-work gate recompute), `205` (complete); `routes/equipment.py:114` (booking), `173` (breakdown), `186` (release); `services.py:160-171` (derivation: count of matching-type `RESERVED`/`ACTIVE` ≥ `required_equipment_count`), `218` (suspend cascade).
  - (c) Adjustment: worded as "on every accepted amendment" (matches the unconditional call, including empty-payload amendments) and "flips … from its birth `false`" so the creation path — which must NOT evaluate coverage at birth — is explicitly preserved; avoided claiming the flag is a standing invariant (contradicted by create_gang) and avoided claiming amendment is the only flip site (start-work gate recomputes too, gangs.py:169).

No other edits were made: Step 7 deleted no tests and fixed no helpers, and the remaining behavior in the diff (the version-bump count itself) was already pinned verbatim by PRD §3.2 — it was an implementation mismatch, not a PRD silence.

## Step 9: Complete PRD — 2026-08-13T01:20:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1327_stevedoring_longshore_labor_ordering/workspace/PRD_COMPLETED.md` produced.

**Source vs output**: PRD_FINALIZED.md (source) 323 lines / 58,587 chars → PRD_COMPLETED.md 323 lines / 61,229 chars. Char-delta: +2,611. Line-delta: 0 (all 20 changes are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts**: 19 ambiguity-pins (inserts/revisions where PRD was silent), 1 mismatch-revision (provisional man-hour line).

Changes, one per bullet:

- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`/`offset` rejected with `ERR_VALIDATION` (400) — middleware.py:162-182
- §2.4 — revise — ambiguity — `version` starts at 1 on creation (was unpinned) — db.py:46
- §2.8 — insert — ambiguity — datetime strings stored/echoed verbatim; naive values interpreted as UTC — middleware.py:140-159, vessels.py:35
- §2.9 — revise — ambiguity — `assigned_equipment_ok` also re-evaluated on every accepted amendment and at every start-work gate evaluation, not only on equipment-assignment change — gangs.py:122, gangs.py:169
- §3.2 — insert — ambiguity — gang order born with `actual_mph` 0, `bonus_eligible` false, `bonus_pool_cents`/`bonus_per_worker_cents` 0 until completion freezes them — gangs.py:57-60
- §3.3 — revise — ambiguity — dispatch batch requires the order itself to be `PLACED`/`DISPATCHING`/`SHORT_MANNED` (else `ERR_INVALID_STATE`); PRD had pinned only the shift-state gate — gangs.py:21,231-232
- §3.3 — insert — ambiguity — a successful batch responds with the updated gang order object, not the created assignments — gangs.py:254
- §3.3 — insert — ambiguity — a bump (unlike a no-show) is not gated on the shift being `IN_PROGRESS` — assignments.py:121-133 vs 104-118
- §3.3 — revise — ambiguity — suspension cascade bumps the worker's `OFFERED` assignments in creation order, each bump triggering its auto-offer in turn — workers.py:90-96
- §3.3 — insert — ambiguity — `INACTIVE` transition carries neither the refusal guard nor the cascade (accepted with outstanding assignments); same-status payloads accepted and still increment version — workers.py:77-97
- §3.4 — revise — ambiguity — duplicate `unit_code` rejected with `ERR_VALIDATION` (400) (no dedicated error id exists in the catalogue) — equipment.py:24-26
- §3.4 — insert — ambiguity — booking imposes no requirement on the gang order's lifecycle state — equipment.py:73-115
- §3.5 — insert — ambiguity — short-manned start with zero checked-in workers rejected with `ERR_INVALID_STATE` (error id previously unnamed) — gangs.py:160-161
- §3.5 — revise — ambiguity — `stoppage_minutes` is an integer — moves.py:35
- §3.6 — insert — ambiguity — `gang_order_id` may be supplied under non-`GANG` scopes; must resolve and is stored — safety.py:26-28,38
- §3.7 — insert — ambiguity — `fault_pct` supplied on a `DENIED` decision: integer recorded as-is without range check, non-integer ignored — claims.py:80-83
- §3.8 — insert — ambiguity — pre-approval timesheet shape: pay-breakdown fields null, `bonus_cents` zero, `submitted_by_user_id` null — timesheets.py:53-59
- §3.9 — revise — ambiguity — invoice creation admitted exactly when vessel is `BERTHED`/`WORKING`/`COMPLETED`; `CANCELLED` refuses with `ERR_INVALID_STATE` ("BERTHED or later" was ambiguous for `CANCELLED`) — invoices.py:25-26
- §3.9 — revise — ambiguity — duplicate invoice create rejected with `ERR_INVALID_STATE` (409) (error id previously unnamed) — invoices.py:27-29
- §3.9 — revise — **mismatch** — provisional man-hour line covers every **non-cancelled** gang order (PRD said "every current gang order"; impl excludes `CANCELLED`) — services.py:498-500

Key cross-checks that turned out already pinned (no change): the at-birth `assigned_equipment_ok: false` convention (pinned by PRD §3.2 and asserted by test_01:211), amendment single-version-bump and amendment-time equipment recompute (already pinned by PRD_FINALIZED), forced-list double-booked-vs-ineligible precedence (pinned by §2.5 tier order), all §4 endpoint paths/methods/role sets, and the full §5 error catalogue. All 94 tests pass in all 8 recorded results runs, confirming the implementation aligned to is stable.
