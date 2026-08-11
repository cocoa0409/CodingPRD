# Worklog — task_1121_broadcast_affiliate_relations_network

## Step 1: Create Task Directory — 2026-08-10T19:39:45.547Z

Task directory `tasks/task_1121_broadcast_affiliate_relations_network/` and its `workspace/` subdirectory were pre-created by the launcher (Step 1 auto-index scan skipped per instructions; index pre-assigned as 1121). Verified both exist and are empty. Beginning at Step 2.

## Step 2: Generate Scaffold — 2026-08-10T20:05:18.578Z

All three scaffold artifacts generated, lint-clean.

**Summary**

- **Output directory**: `/home/ubuntu/github/CodingPRD/tasks/task_1121_broadcast_affiliate_relations_network/`
- **Files on disk** (all non-empty, YAML-loadable):
  - `SCAFFOLD.yaml` (96 KB) — top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`. No `scaffold_difficulty_design` / `scaffold_corner_design` keys.
  - `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (86 KB) — single top-level key `scaffold_difficulty_design`.
  - `SCAFFOLD_CORNER_DESIGN.yaml` (79 KB) — single top-level key `scaffold_corner_design`.

**Counts**
- Entities: **15** (Network, StationGroup, Station, Territory, AffiliationAgreement, Program, ClearanceReport, PreemptionRequest, AvailAllocation, RetransSettlement, OutageEvent, OutageCredit, RenewalOffer, ComplianceReport, SyndicationExclusivityClaim)
- State machines: **12** (incl. cyclic PreemptionRequest counter loop, branching RenewalOffer, posture-driven Station and Network)
- Calculations: **7** (incl. dual-variant PROVISIONAL/FINAL retrans share, tiered outage credit, pinned-rounding clearance rate, waterfall avail allocation, half-open interval overlap, two posture constraint-propagation rules)
- Validations: **20** ordered rules across auth/existence/state/safety/constraint/temporal/referential/fiscal categories
- Endpoints: **100** (domain + flat FK reverse-reachability + `/_clock/set_current_utc`)
- Errors: **23**; Roles: **4** (PlatformAdmin, NetworkAffiliateRelations, StationGroupOwner entity-backed, ComplianceAuditor); Concurrency rules: **2** OCC rules on AffiliationAgreement and Station
- Difficulty-design instances: **18** (2 per each of the 9 §0.5 rules — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- Corner-design instances: **32** across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model (one `excluded_because` stub referencing the unauthenticated corner)

**Harder-than-expert features layered in**
- Dual-variant PROVISIONAL vs FINAL retrans settlement (different trailing snapshot, different rounding rule) plus cause-modulated tiered outage credit
- Cyclic counter-round state machine with explicit termination at 3 rounds
- Posture-driven gating at both Station (DARK threshold 240min, strict `>`) and Network (SWEEP_LOCKDOWN at 3 FAILED, DISPUTE_FREEZE on MAJOR-tier PROPOSED offer)
- Two OCC rules with `expected_agreement_version` / `expected_station_version`
- Half-open interval exclusivity windows vs aggregate-capacity avail pool (different interval semantics)
- Segregation-of-duties on renewal-offer accept/reject/withdraw
- Cascading termination → AvailAllocation revocation + Territory exclusivity release
- Period advancement (`/advance-period`) drives auto-transitions (EXPIRING, EXPIRED, posture recompute)

**Lint verdict** (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Orchestrator verification: all three files exist on disk, `yaml.safe_load` clean, SCAFFOLD.yaml confirmed free of both design keys, 100 endpoints.

## Step 3: Copy Shared Files — 2026-08-10T20:05:18.578Z

Copied `./INSTRUCTION.md` → `tasks/task_1121_broadcast_affiliate_relations_network/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T20:12:17.981Z

**File on disk:** `workspace/PRD.md` — 423 lines, 60,234 bytes, non-empty (orchestrator-verified).

**Section list:**
- §1. Introduction (3 paragraphs — business context, system scope, sweep-period model)
- §2. Global Specifications & System-Wide Principles
  - §2.1 User and Role-Based Access Control (all 4 roles with identity prose)
  - §2.2 API Response Structure (verbatim canonical block)
  - §2.3 Pagination (limit 10/1/100, offset 0, created_at ascending)
  - §2.4 Common Resource Properties and the Optimistic Currency of `version`
  - §2.5 Nested Resource Resolution and Path Parameter Scoping
  - §2.6 Optimistic Concurrency Control on High-Contention Writes
  - §2.7 Precision, Rounding, and Integer-Cent Accounting
  - §2.8 Logical Clock and Sweep Periods
  - §2.9 Network and Station Posture Derivation
  - §2.10 Validation Ordering (all 20 priorities in canonical sequence)
- §3. Business Logic & Workflows (10 subsections: bootstrap; agreements; preemptions; renewals; clearance; settlements; outages; avails; compliance; exclusivity claims)
- §4. Endpoint Definitions (74-row table; Method / Path / Description / Authorized Role(s) only)
- §5. Error Code Catalogue (23-row table; Error ID / HTTP Status Code only)

**Scaffold coverage:** all 15 entities, 11 state machines (44 distinct states), 4 roles, 6 calculations (reverse-comp PROVISIONAL vs FINAL variants, outage credit tiers and cause multipliers, clearance-rate pinned divide-then-round-to-4-decimals, avail waterfall with created_at/size tie-break, half-open window overlap, station and network posture precedence), 20 ordered validations, 2 OCC concurrency rules (`expected_agreement_version` → `ERR_STALE_AGREEMENT_VERSION` 412; `expected_station_version` → `ERR_STALE_STATION_VERSION` 412), 23 error codes, and all endpoints (network/station-group/station/territory/program/agreement/renewal-offer/clearance/preemption/avail/settlement/outage-event/outage-credit/compliance/exclusivity-claim resources, flat reverse-reachability GETs, `advance-period`, and `/_clock/set_current_utc`) received prose coverage.

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 76 required, 76 present, 0 missing — PASS (initial run missed `status` and `to_iso8601`; both added in §2.4 and §2.8 respectively, then re-verified).
- Contract 2 (Rule Coverage): all 23 error IDs in prose, all 44 state strings in prose, all 4 role names, all 15 entity names, both OCC rules expressed with write endpoint + occ_field + error_id + http_status, all enum values present — PASS.
- Contract 3 (§3 Path Purity): 395 backtick tokens scanned inside §3, 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS.

Constraint compliance: subagent did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any other `tasks/task_*/` directory.

## Step 5: Generate Unit Tests — 2026-08-10T20:30:04.730Z

**Files generated** under `/home/ubuntu/github/CodingPRD/tasks/task_1121_broadcast_affiliate_relations_network/`:

- **test_helpers/ — 9 files** (~66 KB): `__init__.py`, `types.py`, `api_client.py` (48 endpoint methods + 13 flat reverse-reachability GETs), `api_errors.py` (registers 23 error→status mappings with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (with mandatory `make_station_group_owner_headers(sg_id)` for the `entity_backed:StationGroup` role), `fixtures.py` (composite scenarios including `setup_basic_scenario`, `drive_network_into_sweep_lockdown`, lifecycle walkers for clearance/compliance/outage/preemption/avail/settlement/renewal/exclusivity entities).

- **test_suite/ — 14 files** (~110 KB): `conftest.py` + 13 test modules organized by concern (bootstrap, auth/RBAC, agreement lifecycle, clearance reports, preemption lifecycle, preemption quota & lockdown, avail pool, outages & credits, retrans settlements, renewal offers, exclusivity claims, validation rules, list endpoints).

**Test counts** — 68 tests collected:
- **Queue A (Difficulty): 36 tests** — every one of the 18 difficulty instances has exactly 2 tests (≥2 target met).
- **Queue B (Corner): 32 tests** — 30 unique corner instances covered, two of which are covered twice (`outage_credit_tier_boundaries`, `preemption_quota_boundary_exactly_10_percent`).

**Instances skipped (2):**
1. `Corner/errors/err_unauthenticated_covered` — `excluded_because:` stub (per §2.1, stubs are NOT translated; the owning difficulty instance covers it).
2. `Corner/entities/station_group_aggregate_retrans_defaults_zero` — PRD §3.1 describes `aggregate_retrans_cents` as "a rolling four-period sum … recomputed on every settlement commit and reconcile" but never states its initial value; under the `computed-field` / `default-value` Silence patterns, a PRD-only reader could legitimately omit a "starts at 0" guarantee. Skipped without weakening.

**Verification:**
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → COMPILE_OK
- `pytest test_suite/ --collect-only -q` → **68 tests collected in 0.06s**, no errors
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line, copied verbatim from the source yaml's `name:` field; all tags resolve to real instances.

## Step 6: Generate Implementation — 2026-08-10T20:30:04.730Z

### File list (under `workspace/implementation/`)
- `start.sh` (executable) — guarded `pip install`, then `exec python3 app.py` reading `$PORT` (default 10000), binding 0.0.0.0
- `requirements.txt` — Flask 3.0.3
- `app.py` — Flask factory, blueprint registration, error handlers
- `db.py` — in-memory `Store` (dicts keyed by id), `logical_clock_utc` defaulting to `2026-05-01T00:00:00Z`, ISO helpers
- `errors.py` — `ApiError` class + all 23 error IDs from PRD §5 with their HTTP statuses
- `response.py` — envelope helpers producing the scaffold-defined `{meta, response_type, data}` shape with pagination fields in `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role membership check
- `routes/` — `networks.py`, `stations.py`, `territories.py`, `programs.py`, `agreements.py`, `renewal_offers.py`, `clearance_reports.py`, `preemptions.py`, `avail_allocations.py`, `retrans_settlements.py`, `outages.py`, `compliance_reports.py`, `exclusivity_claims.py`, `clock.py`
- `services/` — `serializers.py` (per-entity view), `posture.py` (Station + Network posture derivation with precedence rules), `calculations.py` (outage credit tiers, clearance rate 4-dp half-up, provisional round-half-up vs final ceiling, group aggregate recompute), `lifecycle.py` (time-triggered EXPIRING/LAPSED transitions, advance-period cascade)

### Endpoint counts
- **Scaffold declares 100 endpoints** (`grep -c "^- method:" SCAFFOLD.yaml` = 100)
- **Implementation registers 100 routes** (Flask `url_map` enumeration = 100) — all 14 nested resource groups plus all 13 flat reverse-reachability GET routes plus `/_clock/set_current_utc`

### Boot verification
- `python3 -m py_compile` passes on every `.py` file
- `PORT=18233 bash start.sh` booted cleanly; `POST /networks` (PlatformAdmin) returned HTTP 201 with the correct envelope; `GET /networks` returned the paginated list envelope; missing headers returned 401 `ERR_UNAUTHENTICATED` with the correct error envelope; `POST /station-groups` returned 201
- Server killed cleanly

### Scope notes (deliberate choices)
- **Storage**: pure in-memory `Store` dicts; no files, no SQLite, no seeding — every `start.sh` re-launch wipes state, matching the per-test-server isolation contract
- **Logical clock** lives on `store.logical_clock_utc` (single global) and is mirrored onto each `Network.current_utc` on set; on set, time-triggered transitions (`ACTIVE`→`EXPIRING`, `RENEWAL_NEGOTIATION`→`LAPSED`) fire for every network
- **Preemption-quota cumulative hours** interpreted as summing APPROVED preemptions on the same station + agreement (period-scoping is implicit via station+agreement since period_index isn't stored on PreemptionRequest per the scaffold entity definition)
- **Outage-credit linkage at commit**: PENDING credits on the same station whose OutageEvent's `period_index` matches the settlement's `period_index` are flipped to APPLIED with `settlement_id` populated (per PRD §3.6 "applies PENDING OutageCredits" and the APPLIED transition trigger)
- **`_add_months`** for renewal term extension uses calendar-month arithmetic with day-clamping
- **Cascade avail-revocation on terminate** only fires from `ACTIVE` (not `EXPIRING`), per PRD §3.2

## Step 7: Run Tests and Iterate — 2026-08-10T20:41:03.641Z

**Route-parity pre-sweep gate result:** 0 missing, 0 extra (100 routes match scaffold after normalizing path-parameter placeholder names — `{aid}`/`{pid}`/etc. in impl vs `{id}` in scaffold).

**Iterations run:** 3 sweeps × 8 parallel rounds each.
- Iteration 1: 3/68 passed per round (65 failures shared across rounds — fixture precondition broken).
- Iteration 2: 63/68 (5 unique failures).
- Iteration 3: **66/66 in all 8 rounds — clean exit.**

**Tests deleted (PRD-silence / collapse category):**
- `test_07_avail_pool.py::TestAvailPoolConservationUnderRevoke::test_revoke_frees_pool` — ENUM-MEMBERSHIP-ONLY collapse: PRD §3.8 names only `CLAIMED → REVOKED` for desk-initiated revoke; the test asserted `CONFIRMED → REVOKED` restores headroom, a transition PRD does not authorize.
- `test_07_avail_pool.py::TestAvailPoolConservationUnderRevoke::test_confirm_then_revoke_restores_headroom` — same collapse pattern as above (CONFIRMED→REVOKED asserted, PRD silent on that transition).

**Fixes applied to test_suite/:**
- `test_05_preemption_lifecycle.py` — added missing imports `make_platform_admin_headers` and `make_station_group_owner_headers` to fix `NameError` in `test_begin_review_blocked_when_agreement_not_active`.
- `test_09_retrans_settlements.py::test_commit_blocked_when_agreement_terminated` — added `setup_clock("2026-11-01T00:00:00Z")` before `terminate_agreement` so the agreement transitions to `EXPIRING` first; PRD §3.2 waives the no-DRAFT-settlement check when terminating from `EXPIRING` (but not from `ACTIVE`).

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/:**
- `workspace/implementation/routes/clock.py::set_current_utc` — PRD §2.8 defines the logical clock as a server-wide mechanism independent of any `Network` ("At server startup the clock defaults to 2026-05-01..."). Removed the `err_not_found("no network exists to apply clock to")` short-circuit when `store.networks` is empty; endpoint now updates the clock and returns a small echo payload. This unblocked 65 tests whose fixture calls `setup_clock()` before any network exists.
- `workspace/implementation/routes/exclusivity_claims.py::validate_exclusivity_claim` — reordered validation checks to match PRD §2.10's canonical sequence: window-overlap (step 10) now runs before claimant-holds-exclusivity (step 14). Previously the holder check fired first and produced `ERR_CLAIMANT_NOT_HOLDER` where PRD demanded `ERR_NO_WINDOW_OVERLAP` for adjacent windows.

Orchestrator verification: all 8 `results.{1..8}.json` files present on disk, each `passed=66 total=66` (ALL 8 ROUNDS PASS); `sweep.log` ends with `SWEEP_DONE 8 results files`.

## Step 8: Finalize PRD — 2026-08-10T20:47:02.531Z

`workspace/PRD_FINALIZED.md` written (orchestrator-verified on disk: 423 lines, 60,758 bytes).

## Line counts
- PRD.md: 423 lines; PRD_FINALIZED.md: 423 lines; 0% line-count delta (one in-place line revision, no lines added or removed).

## Changes
- **§2.8 — revise (line 121)** — pinned that the logical clock is a single server-wide value independent of any `Network`, that `POST /_clock/set_current_utc` is not network-scoped and succeeds even when zero networks exist, that networks mirror the server clock (late-created networks inherit its current value at creation), and that the success response `data` carries the new clock value (a Network object reflecting the new `current_utc` when networks exist, otherwise an echo object containing `current_utc`) — `workspace/implementation/routes/clock.py:16-49` (zero-network success at lines 47-48), `workspace/implementation/db.py:27-28` (single global clock), `workspace/implementation/routes/networks.py:66` (inheritance at creation).

## Step-7 items judged already-pinned by PRD (verbatim prose kept, no edit)
- **§3.8 revoke (2 deleted tests)**: PRD §3.8 names only `CLAIMED → REVOKED` for desk-initiated revoke, the §4 table row repeats `CLAIMED → REVOKED`, and §2.10 step 4 makes any unnamed source state `ERR_INVALID_STATE`; impl `avail_allocations.py:154-155` enforces exactly that. The deleted tests asserted a `CONFIRMED → REVOKED` transition the PRD never authorized — test overreach, not PRD silence.
- **§3.2 termination waiver (test_09 fixture fix)**: PRD §3.2 already states verbatim "the check is waived when terminating from `EXPIRING`"; impl `agreements.py:189-193` gates the DRAFT-settlement check on `prior_status == "ACTIVE"`. Pure fixture bug.
- **§2.10 exclusivity-claim ordering (impl fix)**: PRD §2.10's canonical numbered sequence (step 10 window-overlap before step 14 claimant-holder) already pinned the order; §3.10's bullets are an unordered set ("Three preconditions, all enforced"). Impl was corrected to match the PRD, not vice versa.
- **test_05 import fix**: pure fixture `NameError`, no behavioral content.

## Per-edit pre-edit search log
Edit 1 (§2.8 clock):
- (a) Subject: server-wide logical clock and `set_current_utc` behavior with zero networks, including response payload.
- (b) Paths enumerated and read: `implementation/routes/clock.py` (whole file — endpoint, mirroring loop, echo vs network-view return), `implementation/db.py` (global `logical_clock_utc`, default, `parse_iso`/`format_iso`), `implementation/routes/networks.py:66` (new network inherits clock), all `current_utc` readers via grep — `agreements.py:154` (activation gate), `outages.py:85` (future-outage check), `renewal_offers.py:146` (180-day renewal eligibility), `services/lifecycle.py:15` (time transitions), `services/serializers.py:13` (view exposes `current_utc`), plus `response.py` (envelope) and test-side call sites (`test_helpers/fixtures.py:40-43`, `api_client.py:7-8`) confirming no test asserts the response body beyond success.
- (c) Wording adjustments: deliberately under-determined on *which* Network object is returned when networks exist ("a `Network` object reflecting the new `current_utc`") since impl returns the last-touched one by dict order and every network is updated; stated the echo payload only for the zero-network branch; added the late-created-network inheritance clause to stay consistent with `networks.py:66`; avoided claiming anything about posture recompute on clock-set (impl recomputes postures, but it is not separately observable beyond transitions the PRD already covers).

## Step 9: Complete PRD — 2026-08-10T21:02:00.141Z

`workspace/PRD_COMPLETED.md` written (orchestrator-verified on disk: 425 lines, 68,488 bytes) — a minimal patch over `PRD_FINALIZED.md`, all in-paragraph inserts/revisions, no new sections (headers verified identical).

**Size**: PRD_FINALIZED.md 423 lines / 60,758 chars → PRD_COMPLETED.md 425 lines / 68,488 chars (char-delta +7,730). 40 lines revised, 2 lines added.

**Counts**: ambiguity-pins: 24; mismatch-revisions: 9. (Counted per distinct behavior pinned/fixed, not per edited line.)

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl source):

- §1 — revise — mismatch — clock no longer described as advancing `current_period_index`/rolling counters/expiring claims; those are the separate advance-period action — routes/clock.py:34-44 vs services/lifecycle.py:55-78.
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — routes/networks.py:26-35 (same helper in every route module).
- §2.4 — revise — mismatch — `version`/`updated_at` no longer claimed to change on "every mutation"; pinned: version increments only on state-machine-transition endpoints and enumerated §3 side effects; derived recomputations (posture, period-advance rollover/expiry, rate updates, territory holder, group aggregate, clock propagation) bump neither; `Network.version`/`StationGroup.version` stay 1 — services/posture.py:36-39, services/lifecycle.py:57-78, routes/networks.py:92-100, routes/clearance_reports.py:144-147.
- §2.5 — insert — ambiguity — unknown paths and unsupported methods return `ERR_NOT_FOUND` (404) — app.py:50-56.
- §2.8 — revise — mismatch+ambiguity — non-decreasing clock violation → `ERR_INVALID_REQUEST` (400); clock-set response carries the most recently created network; clock set recomputes all postures and does not expire avail claims — routes/clock.py:32-49, services/lifecycle.py:66-77.
- §2.8 — insert — ambiguity — `clearance_rate_current_period` is not reset by period advance — services/lifecycle.py:60-65.
- §2.10 — insert — mismatch — deviation note: renewal-offer creation orders rate-sum → term length → agreement OCC → alternating-turns/state; settlement commit orders state → station OCC → agreement-ACTIVE → duplicate-COMMITTED — routes/renewal_offers.py:111-163, routes/retrans_settlements.py:130-153.
- §2.10 — revise — mismatch — 400-class checks (malformed payload, missing fields, bad enum values, dangling foreign keys) run after auth/authz/scoping (steps 1–3), not "before any of the above checks" — e.g. routes/stations.py:51-63, routes/preemptions.py:69-91.
- §3.1 — revise — mismatch — network `current_utc` inherits the server clock's current value, not "the default clock" — routes/networks.py:66.
- §3.1 — revise — ambiguity — `aggregate_retrans_cents` starts at 0; window pinned to `period_index` in [current−3, current] over COMMITTED/RECONCILED settlements — services/calculations.py:98-127, routes/networks.py:119.
- §3.1 — revise — mismatch — station `call_sign` and territory `dma_code` uniqueness is not enforced; `station_group_id` must exist (400) — routes/stations.py:61-63, routes/territories.py:49-57.
- §3.1 — insert — ambiguity — `avail_minutes_local_allocatable > avail_minutes_total` → `ERR_INVALID_REQUEST` (400) — routes/programs.py:73-74.
- §3.2 — insert — ambiguity — submit precondition violations → `ERR_INVALID_STATE` (409) — routes/agreements.py:129-140.
- §3.2 — insert — ambiguity — activate before `term_start_utc` → `ERR_INVALID_STATE`; activation proceeds with no holder set when no territory covers the DMA — routes/agreements.py:154-178.
- §3.2 — revise — ambiguity — EXPIRING window pinned (`term_end−90d ≤ current_utc < term_end`), version increments, and ACTIVE/EXPIRING agreements never lapse past `term_end` — services/lifecycle.py:21-27.
- §3.2 — insert — ambiguity — terminate-from-ACTIVE cascade increments each revoked allocation's version — routes/agreements.py:204-211.
- §3.2 — revise — mismatch — lapse condition pinned: `current_utc ≥ term_end` AND no offer in PROPOSED/COUNTERED (not merely "without accepting") — services/lifecycle.py:27-40.
- §3.3 — insert — ambiguity — preemption creation requires existing `program_id`/`agreement_id` (400), with no same-network/same-station scoping — routes/preemptions.py:88-91.
- §3.3 — insert — ambiguity — begin-review with non-ACTIVE/EXPIRING agreement → `ERR_INVALID_STATE` — routes/preemptions.py:141-143.
- §3.3 — revise — mismatch — quota cumulative pinned to all APPROVED requests on the same station under the same agreement (no per-period reset) — routes/preemptions.py:166-188.
- §3.3 — revise — mismatch — approval no longer "flags FILED/AUDITED clearance reports for recompute"; only station posture recompute + version bump — routes/preemptions.py:189-193.
- §3.3 — insert — ambiguity — disjoint counter window → `ERR_INVALID_REQUEST` (400) — routes/preemptions.py:228-230.
- §3.4 — insert — ambiguity — premature first offer / first offer on wrong agreement state → `ERR_INVALID_STATE`; same-role counter-offer → `ERR_INVALID_STATE` — routes/renewal_offers.py:133-163.
- §3.4 — revise — mismatch — round_index/`renewal_round_count` pinned: counter-offers take prior `round_index`+1 without touching the agreement; post-reject/withdraw offers are allowed from RENEWAL_NEGOTIATION and set `round_index` = incremented `renewal_round_count` — routes/renewal_offers.py:126-163.
- §3.4 — revise — mismatch — accept permitted from PROPOSED **or COUNTERED**; COUNTERED offers may themselves be accepted — routes/renewal_offers.py:209-210.
- §3.4 — insert — ambiguity — term extension uses calendar-month arithmetic with day-of-month clamp — routes/renewal_offers.py:76-88.
- §3.5 — revise — ambiguity — filing requires an agreement in ACTIVE/EXPIRING/RENEWAL_NEGOTIATION (precedence order; else `ERR_INVALID_STATE`); station `clearance_rate_current_period`/posture updated only when the report's period equals the current period; zero-obligation rate is 0.0 — routes/clearance_reports.py:63-69, 133-147, services/calculations.py:49-51.
- §3.5 — insert — ambiguity — resolve-disputed with rate ≥ 0.85 → `ERR_INVALID_STATE` (409) — routes/clearance_reports.py:186-187.
- §3.6 — insert — ambiguity — settlement creation requires existing `agreement_id` (400) but not ACTIVE; `net_retrans_cents`/`outage_credit_cents` set at commit, unchanged at reconcile — routes/retrans_settlements.py:76-77, 249-250.
- §3.6 — revise — ambiguity — commit credit linkage pinned: PENDING credits on the station whose outage event's `period_index` equals the settlement's; their sum is stored as `outage_credit_cents`; provisional discount reads the group's stored aggregate before this commit's recompute; outage counter left unchanged (was "consumed into the credit math") — routes/retrans_settlements.py:155-203.
- §3.6 — insert — ambiguity — premature reconcile → `ERR_INVALID_STATE`; FINAL trailing window pinned to `period_index` in [current−4, current−1] — routes/retrans_settlements.py:214-248.
- §3.7 — insert — ambiguity+mismatch — confirm with `duration_minutes` < 1 → `ERR_INVALID_STATE`; outage counter incremented only when the event's period is the current period — routes/outages.py:141-164.
- §3.7 — insert — ambiguity — forfeit violations (non-PENDING credit, non-PLANNED_MAINTENANCE cause) → `ERR_INVALID_STATE` (409) — routes/outages.py:224-228.
- §3.8 — revise — mismatch — DARK confirm → `ERR_INVALID_STATE`; deleted the created_at-chronological/tiebreak processing prose (impl has no queue/tiebreak); capacity evaluated at confirm time — routes/avail_allocations.py:127-147.
- §3.8 — insert — ambiguity — period-advance expiry does not increment allocation version — services/lifecycle.py:66-77.
- §3.9 — insert — ambiguity — resolve-pass/fail gate violations → `ERR_INVALID_STATE` (409) — routes/compliance_reports.py:158-159, 173-174.
- §3.10 — insert — ambiguity — respondent-equals-claimant check runs last at validation and fails with `ERR_INVALID_REQUEST` (400) — routes/exclusivity_claims.py:152-153.
- §4 intro — insert — ambiguity — nested list endpoints accept `status`; period-bearing lists accept `period_index`; compliance lists accept `report_kind` — e.g. routes/clearance_reports.py:112-122, routes/compliance_reports.py:104-117.
