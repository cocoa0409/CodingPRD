# Worklog — task_1822_railcar_leasing_fleet_management

## Step 1: Create Task Directory — 2026-08-14T19:01:00.000Z

Task directory `tasks/task_1822_railcar_leasing_fleet_management/` and `workspace/` were pre-created by the pipeline launcher (index 1822 assigned by the user; no index scan performed per instructions). User difficulty directive: harder than expert level.

## Step 3: Copy Shared Files — 2026-08-14T19:02:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1822_railcar_leasing_fleet_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T19:47:30.000Z

All checks pass. The scaffold for task 1822 is complete and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

| Element | Count |
|---|---|
| Entities | 15 (Lessee, Railcar, LeaseAgreement, TariffRate, LeaseAssignment, MileageReport, CarHireStatement, RepairAuthorization, CleaningRecord, DamageAssessment, ComplianceDirective, RetrofitOrder, RetirementCase, CapitalPool, PurchaseCommitment) |
| State machines | 13 (cyclic shop/return loop on Railcar, revision cycle on RepairAuthorization, dispute cycles on MileageReport/CarHireStatement/DamageAssessment, deferral cycle on RetrofitOrder, reject-revert on LeaseAgreement, branching retirement) |
| Calculations | 9 (incl. dual-variant car-hire settlement CURRENT-vs-PINNED tariff, dual-variant retrofit penalty ACCRUED-vs-ASSESSED, per-line-rounded damage billing, pinned-order lease proration, tiered mileage credit, pool waterfall) |
| Validations | 12 ordered priority rows (auth → ownership/SoD → existence → shape → state → safety → referential → temporal → constraint → fiscal) |
| Endpoints | 95 (incl. `POST /_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default) |
| Errors | 50 |
| Roles | 7 (SystemAdmin, LeaseAdmin, FleetPlanner, MaintenanceController, BillingAnalyst, ComplianceOfficer, entity-backed LesseeRep; segregation-of-duties on retirement approve) |
| Concurrency rules | 3 true OCC races (lease amend, tariff amend, pool commitment) |
| §1.8 non-stub instances | 22 (all 9 rules ≥2 instances; rules 2/3/7/9 carry 3 each) |
| §1.9 instances | 62 total: 54 non-stub + 8 `excluded_because` stubs pointing at §1.8 |

## Key design properties

- **Dual-variant calcs in different domains**: billing (provisional current-tariff vs final pinned-tariff, divergence 253000 vs 226750 on identical inputs) and compliance (accrued 1125000 vs assessed 375000 penalty).
- **Combinatorial modes a/b/c all exercised**: repair split branching (30000 vs 100000 on same estimate), damage billing rounding order (77625 per-line vs forbidden 77624 sum-then-round — one-cent trap verified by computation), proration evaluation order (80000 pinned vs 100000 naive).
- **Cascades**: directive promote (depth 2: posture flip → mass assignment cancel) and statement finalize (depth 3: finalize → balance debit → auto-suspension at 224000 > 200000 limit).
- **Priority conflicts in different category pairs**: state-beats-fiscal on settle, safety-beats-temporal on assignment (age-50 car + overlapping window → ERR_AGE_LIMIT_EXCEEDED).
- **Two interval semantics**: inclusive assignment windows with 3-day commodity-turnaround buffer vs half-open tariff windows where adjacency is legal.
- All numeric asserts were pre-computed by code (dates, fees, tier boundaries at exactly 120000 miles, 90-day termination-fee cap = 225000, etc.).

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (624 calls scanned). Additional self-audits passed: every `grounds:` reference resolves, every error code is triggered somewhere, every status enum value is produced by a transition, no forbidden concurrency vocabulary.

## Step 4: Generate PRD — 2026-08-14T19:57:00.000Z

All audits pass. The PRD is complete.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/workspace/PRD.md`
**Line count:** 460 lines

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

### Coverage audit (per §1.x)

- **§1.0 response envelope** — 1/1 translated: §2.2 emitted byte-for-byte verbatim from `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`); §2.3 covers pagination defaults (limit 10, min 1, max 100, offset 0), `created_at` ascending sort, and the four `meta` fields.
- **§1.1 entities (15)** — 15/15 covered in §3 narratives (lessee, railcar, lease, tariff, assignment, mileage report, statement, repair, cleaning, damage, directive, retrofit, retirement, pool, commitment). All 130 field names (entity fields + endpoint input/query/path params + computed-view output keys) appear verbatim in backticks — Contract 1 PASS. Structured field content (types, defaults, nullability, computed derivations) is expressed per entity.
- **§1.2 state machines (13)** — 13/13 covered; all 61 transitions rendered with from/to state pairs, preconditions paired to their exact `error_id`, and every side effect (cascades, version-relevant mutations, counter increments, `status_before_shop` save/restore, conservation deltas) stated in prose.
- **§1.2.1 concurrency rules (3)** — 3/3 expressed in §2.11 with write capability, `expected_lease_version` / `expected_tariff_version` / `expected_pool_version`, parent-version mismatch, and `ERR_STALE_VERSION` (412); framed purely in stale-version terms.
- **§1.3 calculations (9)** — 9/9 expressed in precise prose with pinned evaluation/rounding order: mileage credit (120,000 threshold, 80% excess, boundary-exactness note), car-hire settlement (both provisional/final variants, cap, rounding order), repair split (25,000-cent allowance, 40% excess, FULL_SERVICE default when unlinked), damage schedule (14,500/hr labor, severity multipliers 1.00/1.25/1.50, betterment at age 30 / 25%, per-line-then-sum rounding), lease proration (6-step pinned order), retrofit penalty (accrued vs assessed variants), fleet utilization (2-decimal half-up, empty-fleet 0.0), capital pool waterfall (commit-cancel exact restoration invariant), cumulative-miles conservation (delta-only revalidation invariant).
- **§1.4 validations (12 priorities)** — 12/12 expressed in §2.6 as an explicit ordered list with categories, trigger conditions, and error ids; cross-references to §2.7/§2.10 and scattered §3 trigger prose.
- **§1.5 endpoints (95)** — 95/95 in the §4 table (4 columns: Method, Path, Description, Authorized Role(s)); side effects and request inputs narrated in §3; §3 contains zero path/method backticks (Contract 3 PASS, 677 tokens scanned).
- **§1.6 errors (50)** — 50/50 in the §5 two-column table; all 50 ids also named in §2/§3/§4 prose near their triggers.
- **§1.7 roles (7)** — 7/7 in §2.1 with exact spelling; identity semantics translated (`LesseeRep` entity-backed via `Lessee.id`; the other six opaque), plus the SoD exception on retirement approval.

### Intentional judgment calls (no omissions)

1. `ERR_LESSEE_HAS_OPEN_LEASES` appears in the scaffold's Lessee state-machine preconditions but is absent from the §1.6 error catalog. The PRD mirrors both faithfully: named in §3.1 prose (409), absent from the §5 table (which mirrors the catalog's 50 entries exactly).
2. The scaffold's assignment deliver/cancel side effects say "Railcar RESERVED -> ON_LEASE/AVAILABLE", but the Railcar state machine has no `RESERVED` state; the canonical transition is `AVAILABLE → ON_LEASE`. The PRD follows the state machine (the governing artifact) and does not invent a `RESERVED` state.
3. §4 status-code paragraph states the 201-create / 200-modify rule per the skill spec; the clock endpoint's 200 and the scaffold's per-endpoint codes are consistent with this.

## Step 5: Generate Unit Tests — 2026-08-14T20:38:00.000Z

Generation complete and all audits pass. Summary:

## Files written

**test_helpers/** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/test_helpers/`)
- `types.py` — 15 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4), 20 domain enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 72 methods covering every PRD §4 endpoint incl. `POST /_clock/set_current_utc`
- `api_errors.py` — 51-entry `ApiErrorId` + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — 15 per-entity asserters + `assert_pool_available_invariant` (waterfall)
- `factories.py` — 14 payload factories incl. `damage_line_item`
- `constants.py` — thresholds (120000-mile tier, 80% cap/excess, 25000 wear allowance, 40%, 14500 labor, betterment 30/25, age 50, 90-day fee cap, 3-day buffer, default clock)
- `test_users.py` — `TEST_USERS` for all 7 roles + per-instance builders; `make_lessee_rep_headers(lessee_id)` for the entity-backed role, planner/officer builders for retirement SoD
- `fixtures.py` — composite setups: `setup_active_lease_scenario`, `setup_provisional_statement`, tariff pairs, mileage submit/validate (identity-threaded), repair/shop helpers, `close_open_damage_assessments` (handles the return-cascade DRAFT from PRD §3.4 before settle), directive/retrofit/retirement/pool helpers, `set_clock`
- `__init__.py` — barrel (framework + PRD-specific)

**test_suite/** (conftest + 11 files, 5140 lines total): `test_01_registry_and_envelope` (9), `test_02_security_and_rbac` (6), `test_03_lease_agreements` (5), `test_04_tariffs` (5), `test_05_assignments_and_safety_gates` (13), `test_06_mileage_and_statements` (19), `test_07_repairs_and_shop` (9), `test_08_damage_and_settlement` (9), `test_09_compliance` (9), `test_10_retirement_and_capital` (9), `test_11_utilization` (2).

## Counts
- **Total: 95 tests** — Queue A: 44 (all 22 difficulty instances translated, ≥2 tests each, 0 skipped). Queue B: 51 (of 54 non-stub corner instances).
- **Queue B skips (3)**:
  1. `lease_create_with_unknown_lessee_returns_not_found` — PRD §2.6 existence rule is scoped to *path* identifiers ("path identifiers resolve left-to-right"); no PRD sentence derives 404 `ERR_LESSEE_NOT_FOUND` (vs 400) for an unresolvable *body* `lessee_id` — fails unique derivability.
  2. `unknown_lease_id_not_found_beats_body_shape` — same gap: existence-beats-shape ordering is stated only for path identifiers / nested parents (§2.6 prose, §2.12), so a body-FK-vs-shape priority assertion is not uniquely derivable.
  3. `assignments_filtered_list_by_railcar` — PRD §4 names list endpoints only as "(filtered)"; the `railcar_id` query-param name appears nowhere in the PRD.
- 8 `excluded_because:` stubs not translated (per spec); all their `difficulty_instance` cross-references verified to resolve.

## Stage 2 self-check
- All 95 test docstrings end with exactly one `Design:` tag; every tag resolves to a real instance in the source yaml (programmatically verified).
- Every difficulty instance has ≥2 tests; every translated corner instance ≥1.
- Verbatim-citation sweep: every quoted PRD span in every docstring has a ≥8-word contiguous fragment surviving literal match against PRD.md — 0 failures.
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code; `pytest --collect-only` succeeds (95 collected).

Notable translation decisions: settle-path tests close the return-cascade DRAFT damage assessment (PRD §3.4/§3.6) so the asserted gate is deterministic; the idempotent-generate test asserts the empty array via the lenient validator (HTTP 200-vs-201 on a zero-creation batch is not PRD-pinned); OCC tests capture versions dynamically rather than hard-coding.

## Step 6: Generate Implementation — 2026-08-14T20:36:00.000Z

Implementation complete and verified against five smoke-test rounds (all passing, each on a freshly booted server).

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/workspace/implementation/`:

- `start.sh` — guarded install (`python3 -c "import flask"` check), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry, custom JSON provider (dates serialize as `YYYY-MM-DD`), ApiError/404/405/500 envelope handlers
- `store.py` — in-memory dicts (15 entity stores, **no seeding**), logical clock defaulting to `2026-08-01T00:00:00Z`, id/timestamp/version helpers
- `errors.py`, `envelope.py` — `meta.api_request_id`/`api_request_timestamp` (3 fractional digits), `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more`
- `http_util.py` — auth (X-User-ID/X-User-Role, 7 roles), typed body validators, pagination parsing (default 10, min 1, max 100)
- `calc.py` — all 9 calculations with pinned ROUND_HALF_UP ordering (Decimal-based)
- `domain.py` — serializers, balance ledger with auto-suspension, lazy lease EXPIRED evaluation, compliance-posture recompute, tariff lookup/overlap, LesseeRep ownership
- `settlement_service.py` — provisional/final car-hire settlement variants, M_prev tier accumulation
- `routes/` — 14 blueprint modules covering all resource groups

## Endpoints

**95/95 implemented** (96 Flask rules including the default static route). All 13 state machines (61 transitions), 9 calculations (both settlement variants, both penalty variants, per-line damage rounding, pinned proration order), 12 validation priorities, all 50 catalogued error ids plus `ERR_LESSEE_HAS_OPEN_LEASES` (referenced in PRD §3.1/state machine but absent from the §5 table), 7 roles with entity-backed LesseeRep and retirement SoD, 3 OCC rules (`expected_lease_version`/`expected_tariff_version`/`expected_pool_version` → ERR_STALE_VERSION 412), and the logical clock endpoint.

## PRD ambiguities resolved

- **SoD priority conflict**: PRD §2.6 lists retirement approver≠proposer at both priority 3 and priority 11 — implemented at priority 3 (after role/existence, before state checks), matching the "On retirement approval specifically" wording.
- **Second shop repair while IN_SHOP**: scaffold's start-work precondition (`AVAILABLE`/`ON_LEASE` only) contradicts PRD §3.2's "two overlapping shop repairs keep the car IN_SHOP" — allowed start-work from IN_SHOP, incrementing `open_shop_repair_count` without overwriting `status_before_shop`.
- **Lease date-range check**: validated at approve (per explicit state-machine precondition), not at create or PATCH, since §3.3 describes no create-time ordering rule and amendments can change `end_date`.
- **Lease approve dual-failure order**: `ERR_LESSEE_NOT_ACTIVE` (priority 7) checked before `ERR_INVALID_DATE_RANGE` (priority 10), following §2.6 over the state machine's listed precondition order.
- **Provisional pricing when no current tariff covers the statement month**: falls back to the assignment's pinned rates (PRD silent; keeps statements computable).
- **M_prev scope**: literal scaffold reading — validated loaded miles on the lease for the whole calendar year excluding this statement's (assignment, month) report, with DISPUTED reports contributing retained validated values.
- **`created_at`/`updated_at`/`api_request_timestamp`**: sourced from the logical clock (§2.5: all timestamp arithmetic uses it), formatted with three fractional digits; clock `current_utc` echoes the client's exact `to_iso8601` string.
- **Clock backward sets**: accepted (per-test reboots start at the default; tests may need earlier 2026 dates).
- **LesseeRep read scoping**: single-resource GETs on another lessee's resources → 403; list endpoints filter to own resources; assignment-less repairs (no owner) remain readable.
- **Version bumps**: one increment per entity per request, including cascade targets (cancelled assignments, pool on commitment create, cars on directive promote); lazy EXPIRED transition on read counts as a mutation (+1).
- **Termination-fee double billing**: lease terminate bills the fee, and later assignment settle on a TERMINATED lease bills `termination_fee_cents` again — both side effects are explicit in §3.3/§3.6, implemented as written.

## Step 7: Run Tests and Iterate — 2026-08-14T21:05:00.000Z

All 8 rounds clean: 95/95 passed in every round. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial sweep: 94/95 in all 8 rounds, one consistent failure; post-fix sweep: 95/95 in all 8 rounds).

**Tests deleted:** None. The single failing test traced to a verbatim PRD rule with unique derivability, so it stayed.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** One.

- **File:** `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/workspace/implementation/settlement_service.py`
- **Function:** `m_prev_loaded_miles`
- **Why:** `test_cumulative_miles_exactly_at_threshold_have_no_excess` (test_06) failed in all 8 rounds with `assert 1 == 0` on `tier_excess_miles`. The test sets up July=119000 and August=1000 validated loaded miles (lease-year total landing exactly on the 120,000 threshold), plus a September=1 report validated *before* the August statement is generated. The implementation computed M_prev as *all* validated loaded miles in the calendar year minus this statement's own report — so September's 1 mile leaked into the August statement's "prior accumulation" (119001), producing 1 excess mile instead of 0. PRD §3.7 defines the input as "the **prior accumulated** loaded miles ... in the calendar year of the statement month, excluding this statement" — the definiendum "prior accumulated" is chronologically load-bearing (corroborated by §3.5, which recomputes only same-`(assignment, report_month)` PROVISIONAL statements on validation; the whole-year reading would silently invalidate earlier-month statements with no recompute path). Fix: skip reports whose `report_month` is after the statement month (`if r["report_month"] > statement_month: continue`), keeping the same-calendar-year scope and the exclusion of the statement's own report (the reading under which the PRD's "excluding this statement" clause is non-redundant). The paired boundary test (`test_first_mile_beyond_threshold_prices_at_excess_rate`, M_prev=120000 → excess=1, credit=44) passes under the same fix.

**Verification:** Full 8-round parallel stability sweep after the fix — every round `passed == total` (95/95), no flakiness observed in either sweep.

## Step 8: Finalize PRD — 2026-08-14T21:12:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 460 lines, PRD_FINALIZED.md 460 lines — 0.0% delta (one in-place sentence revision, no lines added or removed).

**Changes (one total):**
- §3.7 (Car-Hire Statements, shared settlement-formula paragraph) — revise — the definition of "prior accumulated loaded miles" gained an explicit chronological pin: only reports for months up to and including the statement month count; a later-month report never contributes to an earlier month's statement regardless of when it was validated. The existing "calendar year of the statement month" scope and "excluding this statement" clause are kept verbatim — impl file `workspace/implementation/settlement_service.py:52-53` (the Step 7 fix `if r["report_month"] > statement_month: continue`), in `m_prev_loaded_miles` (lines 37-60).

**Per-edit pre-edit search log:**
- Edit 1:
  - (a) Subject: the M_prev ("prior accumulated loaded miles") definition's chronological scope in §3.7.
  - (b) Impl paths enumerated and read/grepped: `settlement_service.py:37-60` (`m_prev_loaded_miles`, sole producer — filters: VALIDATED/DISPUTED status, non-null validated miles, same calendar year, `report_month <= statement_month`, same lease via assignment, exclude this statement's own (assignment, month)); `settlement_service.py:69` (`compute_fields`, sole caller, shared by `apply_provisional` line 99 and `apply_final` line 112 → both variants use identical M_prev); all four entry points — `routes/statements.py:67` (generate), `routes/statements.py:153` (dispute recompute), `routes/statements.py:123` (finalize), `routes/mileage.py:154` (validation-triggered recompute); `calc.py:36-41` (`mileage_credit`, pure arithmetic consumer). Repo-wide greps for `m_prev|prior` and `120000|threshold|excess` confirmed no other producer or parallel computation. Test-side evidence read: `test_suite/test_06_mileage_and_statements.py:347-401` (the two boundary tests).
  - (c) Wording adjustment: the pin was placed in the shared-formula paragraph (not the variant-differences paragraph) because M_prev is variant-independent — both provisional and final paths call the same function; phrased as "months up to and including the statement month" plus a non-contribution clause, deliberately leaving the same-month/other-assignment case (impl counts it via `exclude_assignment_id`-scoped exclusion) and the DISPUTED-report inclusion untouched, since Step 7 did not exercise them and the existing PRD text already covers them. No narrowing of any enumerated path.

## Step 9: Complete PRD — 2026-08-14T21:17:00.000Z

All 51 diff hunks match the intended edits exactly. The work is complete. Final verification of the output file state is done — here is the summary.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1822_railcar_leasing_fleet_management/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` 460 lines / 71,205 chars → `PRD_COMPLETED.md` 464 lines / 78,647 chars; char-delta **+7,442** (+4 net lines: one §2.2 bullet, one §2.7 bullet, two §5 table rows; all other changes are in-paragraph inserts/revisions). No new sections added.

**Counts:** 40 ambiguity-pins, 4 mismatch-revisions (44 changes across 51 hunks; §2.3 and §2.4 each carry multiple pins in one paragraph edit).

### Changes

- §2.1 — insert — ambiguity — extended the rejected LesseeRep cross-lessee actions to reads of another lessee's `Lessee` record/lease/single resources, and pinned list-endpoint scoping for LesseeRep (reports, statements, assessments, repairs; unlinked repairs visible to every LesseeRep) — routes/clock_lessee.py:77, routes/leases.py:79, routes/mileage.py:96-97,119, routes/statements.py:79,104, routes/damage.py:104-105,124, routes/repairs.py:98-103,122-124
- §2.2 — insert — ambiguity — `api_request_timestamp` (and all `created_at`/`updated_at`) are logical-clock readings, never wall-clock — envelope.py:11-12, store.py:41-44
- §2.2 — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404); unexpected failure → `ERR_INTERNAL` (500) — app.py:34-49
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or bad `offset` → `ERR_VALIDATION` (400) — http_util.py:151-173
- §2.3 — insert — ambiguity — `created_at` ties break in creation (insertion) order — store.py:59 and every list route's sort key
- §2.3 — insert — ambiguity — `has_more` = `offset` + returned-item count < `total_count` — envelope.py:29
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — store.py:58
- §2.5 — insert — ambiguity — clock set echoes the supplied string verbatim (trimmed), naive offsets read as UTC, unparseable → `ERR_VALIDATION` (400) — routes/clock_lessee.py:21-35
- §2.6 p3 — insert — ambiguity — priority-3 ownership/SoD evaluated as soon as the target resolves: after existence for path targets, after shape+body-FK resolution for mileage-report creation — domain.py:213-221, routes/mileage.py:42-50, routes/retirements.py:88-97
- §2.6 p4 — insert — ambiguity — path ids resolve before the body; body-carried ids resolve after shape validation in the order §3 names them; tariff endpoints use generic `ERR_NOT_FOUND` — routes/tariffs.py:18-23, routes/assignments.py:56-59
- §2.6 p5 — insert — ambiguity — validator strictness: non-empty strings, strict JSON ints/bools, `YYYY-MM-DD` dates, `YYYY-MM` months — http_util.py:74-148
- §2.6 p11 — **revise** — **mismatch** — removed the claim that retirement approver-equals-proposer is checked at priority 11; impl checks it at priority 3 (right after existence, before state legality) — routes/retirements.py:88-97
- §2.7 — insert — ambiguity — added the lessee-termination open-leases gate (`ERR_LESSEE_HAS_OPEN_LEASES`) to the gate list, which read exhaustively — routes/clock_lessee.py:107-117
- §2.10 — insert — ambiguity — "bridges" defined: cleaning's `prior_commodity` = car's `last_commodity` and `next_commodity` = `planned_commodity` — routes/assignments.py:30-42
- §2.11 — insert — ambiguity — OCC comparison placement: after shape (5) and state legality (6) where present, before tariff window re-validation (10) and pool affordability (12) — routes/leases.py:138-144, routes/tariffs.py:93-100, routes/pools.py:72-81
- §3.1 — insert — ambiguity — lessee-termination scan reads stored lease statuses without triggering lazy expiry — routes/clock_lessee.py:107-112
- §3.2 — insert — ambiguity — initial `compliance_posture` derived per §3.11 at creation (can be born `RETROFIT_DUE`/`NON_COMPLIANT`); derivation does not bump `version` — routes/railcars.py:54-57, routes/pools.py:155
- §3.2 — **revise** — **mismatch** — car-state graph now permits start-work while already `IN_SHOP` (second overlapping repair; saved `status_before_shop` untouched, only count increments) — routes/repairs.py:217-229
- §3.3 — insert — ambiguity — lease born `DRAFT` with `submitted_by_user_id` and `early_termination_fee_cents` null — routes/leases.py:48-50
- §3.4 — insert — ambiguity — "previous assignment" for the turnaround buffer: among the car's `SCHEDULED`/`ON_LEASE`/`RETURNED`/`SETTLED` assignments with `scheduled_end` ≤ `scheduled_start`, the latest `scheduled_end` (creation-order ties) — routes/assignments.py:119-133
- §3.5 — insert — ambiguity — report's `railcar_id` recorded as given, never cross-checked against the assignment's railcar — routes/mileage.py:42-47
- §3.7 — insert — ambiguity — statement generation responds 201, `response_type` `array`, no pagination fields in `meta` — routes/statements.py:70, envelope.py:35-38
- §3.7 — insert — ambiguity — `days_on_lease` with null `actual_off_lease_date` runs through month end — calc.py:47-59
- §3.7 — insert — ambiguity — prior-accumulation excludes only this statement's own (assignment, month) reports; other same-lease same-month reports count; `DISPUTED` reports contribute last validated loaded miles — settlement_service.py:37-60
- §3.7 — insert — ambiguity — provisional variant falls back to pinned snapshot when no current window covers the month's first day (still labelled `CURRENT`); governing report = latest-created non-`DISPUTED` report, else latest `DISPUTED` (validated values when present, else reported) — settlement_service.py:9-21,77-89
- §3.7 — insert — ambiguity — recompute clears `dispute_reason` to null — routes/statements.py:155
- §3.9 — insert — ambiguity — pre-authorization accepted only in `UNDER_REVIEW`/`REVISION_REQUESTED`; unlinked repairs have no owner and can never be pre-authorized (403) — routes/repairs.py:128-144
- §3.9 — **revise** — **mismatch** — start-work gate admits `AVAILABLE`, `ON_LEASE`, **or already `IN_SHOP`**; `status_before_shop` saved on first entry only (PRD said AVAILABLE/ON_LEASE only, contradicting its own two-overlapping-repairs rule) — routes/repairs.py:215-229
- §3.10 — insert — ambiguity — cleaning starts with `cleaning_grade_performed`, `cost_cents`, `certificate_ref` null — routes/cleanings.py:39-53
- §3.10 — insert — ambiguity — "most recent `RETURNED`/`SETTLED` assignment" = greatest `actual_off_lease_date`, creation-order ties; no such assignment → no balance posting — domain.py:231-242, routes/cleanings.py:113-119
- §3.10 — insert — ambiguity — damage line-item constraints: non-empty `component`, non-negative int `parts_cents`, non-negative number `labor_hours`, strict bool `replaced` — routes/damage.py:34-72
- §3.10 — insert — ambiguity — assessment's `railcar_id` recorded as given, not cross-checked against the assignment — routes/damage.py:81-84
- §3.11 — insert — ambiguity — formal posture rule: `NON_COMPLIANT` if any `EFFECTIVE` covering directive lacks a `CERTIFIED` retrofit, else `RETROFIT_DUE` if any `ANNOUNCED` one does, else `COMPLIANT` — domain.py:152-167
- §3.11 — **revise** — **mismatch** — announcement re-derives posture under that rule; a car already `NON_COMPLIANT` stays so (PRD said unconditionally "set to `RETROFIT_DUE`") — routes/directives.py:64-68
- §3.11 — insert — ambiguity — `grace_days` zero-or-more when supplied (default 30) — routes/directives.py:38-40
- §3.11 — insert — ambiguity — retrofit creation permits any directive status, no car-type coverage check, duplicate orders coexist — routes/retrofits.py:22-51
- §3.11 — insert — ambiguity — compliance view re-derives posture at read time; `open_directive_ids` in creation order — routes/railcars.py:98-123
- §3.12 — insert — ambiguity — missing/malformed `month` → `ERR_VALIDATION` (400) — routes/railcars.py:129-137
- §3.14 — insert — ambiguity — retirement case's four money fields null until appraisal — routes/retirements.py:30-41
- §3.14 — insert — ambiguity — `fiscal_year` is any integer — routes/pools.py:37
- §4 — insert — ambiguity — missing/unparseable body treated as `{}`; non-object JSON body → `ERR_VALIDATION` (400); unknown body fields ignored — http_util.py:64-71
- §4 table — revise ×14 — ambiguity — named each list endpoint's exact filter parameters (`/railcars`, `/tariff-rates`, `/lease-agreements`, lease-assignments-of-lease "(no query filters)", `/lease-assignments`, `/mileage-reports`, `/car-hire-statements`, `/repair-authorizations`, `/cleaning-records`, `/damage-assessments`, `/compliance-directives`, `/retrofit-orders`, `/retirement-cases`, pool commitments) — the `request.args.get(...)` filter blocks in every list route
- §5 — insert — ambiguity — added `ERR_LESSEE_HAS_OPEN_LEASES` (409) row — routes/clock_lessee.py:115
- §5 — insert — ambiguity — added `ERR_INTERNAL` (500) row — app.py:44-49

**Cross-checks performed:** all 95 endpoints and their role lists match §4 exactly; all 50 error ids raised by the implementation now appear in §5; all 13 state machines, 9 calculations (incl. both settlement variants, both penalty variants, per-line damage rounding, pinned proration order), and the validation-priority chain were walked line-by-line against the routes; tests were consulted only as cross-reference, never as authority.
