# Worklog — task_1342_research_core_facility_scheduling_recharge

Scenario: Research Core Facility Scheduling & Recharge (university core facility) — instrument catalog & booking calendar with training requirement, user rate development (internal/external) & break-even review, usage logging & automated recharge to grants, subsidy/startup fund application, instrument downtime & maintenance contract, priority access & cancellation penalties, annual rate true-up & surplus/deficit carryforward, acknowledgment & publication tracking.

Difficulty directive: harder than expert level.

## Step 1: Create Task Directory — 2026-08-12T23:09:00.000Z

Pre-assigned by pipeline: tasks/task_1342_research_core_facility_scheduling_recharge/ and its workspace/ subdirectory already existed; verified present. No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T00:25:00.000Z

(Resume note: subagent summary was lost when the previous run was killed. Orchestrator verified artifacts on 2026-08-13.) All three scaffold artifacts exist and validate as well-formed YAML: SCAFFOLD.yaml (114,444 bytes; top-level keys scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations — §1.0–§1.7, no scaffold_difficulty_design / scaffold_corner_design keys), SCAFFOLD_DIFFICULTY_DESIGN.yaml (132,109 bytes; single top-level key scaffold_difficulty_design — §1.8), SCAFFOLD_CORNER_DESIGN.yaml (192,498 bytes; single top-level key scaffold_corner_design — §1.9). Files end mid-structure nowhere; tails show complete nested sections. Kept and reused as-is per resume policy.

## Step 4: Generate PRD — 2026-08-13T00:45:00.000Z

All three contracts pass.

**Summary**

Generated `workspace/PRD.md` (427 lines).

**Sections written:**
- §1 Introduction (3 paragraphs — business context, segregation-of-duties/NIH rate discipline/logical clock)
- §2 Global Specifications: 2.1 RBAC + identity translation, 2.2 verbatim response envelope, 2.3 pagination, 2.4 logical clock + time-derived statuses, 2.5 money/precision/rounding discipline, 2.6 common resource properties, 2.7 nested retrieval, 2.8 OCC (three rules), 2.9 validation priority order (41 items enumerated), 2.10 computed statuses + ledger bubble-up
- §3 Business Logic (13 subsections): 3.1 users, 3.2 instruments, 3.3 training, 3.4 grants, 3.5 rate development/break-even, 3.6 booking + preemption, 3.7 cancellation/reschedule/session, 3.8 usage logging + subsidy waterfall, 3.9 recharge batches/entries/dispute loop, 3.10 subsidies/awards, 3.11 maintenance contracts + downtime, 3.12 publications, 3.13 fiscal-year close/true-up
- §4 Endpoint table (4 columns, 87 rows)
- §5 Error catalogue (2 columns, 39 errors)

**Hard-contract reports:**

Field coverage check: entities[].fields + endpoint inputs + common fields: 114 required, 114 present, 0 missing — PASS
Rule coverage check: 41 validations (priority-ordered list in §2.9 with error ids); 3 concurrency_rules OCC rejections with endpoint/occ field/error id/status; 15 state machines (all transitions, preconditions, side effects); 10 calculations as precise prose (rounding order pinned); 87 endpoints in §4 with side-effects narrated in §3 — PASS
Path purity check (§3): backtick tokens scanned ~700; tokens starting with `/`: 0; bare HTTP methods: 0; method+path combined: 0 — PASS

**Coverage decisions:**
- Split §2 into 10 subsections (validation priority list long + load-bearing → own §2.9).
- Used 13 subsections in §3 (15 state machines map cleanly; Grant computed status folded into §2.10 + §3.4; SubsidyAward computed status into §3.10; RechargeEntry lifecycle in §3.9).
- Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml; no other task_* directories touched.
- Embedded constants as business context: OPERATING_OVERHEAD_CENTS 120000 as "120,000 cents ($1,200)"; MAX_RATE_INCREASE_PCT 0.10 as "ten percent / multiplied by 1.10"; RATE_DEVIATION_FLAG_PCT 0.05 as "five percent"; CERT_VALIDITY_MONTHS 12 as "twelve months"; EARLY_CHECKIN_MINUTES 15 as "fifteen minutes"; SECONDS_PER_MINUTE 60 as "divided by sixty".
- Boundary semantics preserved exactly: half-open booking intervals [start_at, end_at + buffer); closed downtime intervals; inclusive expires_at (at = expired); inclusive cancellation-notice boundary (at = free); subsidy waterfall valid_from ≤ t < valid_until.

## Step 5: Generate Unit Tests — 2026-08-13T01:27:00.000Z

All checks pass. Final summary:

## Files written

**test_helpers/** (9 files, under `test_helpers/`):
- `types.py` — 20 status/enum types + 15 entity TypedDicts
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 87, incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 39 error IDs + HTTP map registered via `set_error_http_status_map`
- `assertions.py`, `constants.py` (CERT_VALIDITY_MONTHS=12, EARLY_CHECKIN_MINUTES=15, OPERATING_OVERHEAD_CENTS=120000, rate cap/deviation constants, canonical instrument/rate/booking literals), `factories.py`, `test_users.py` (shared opaque-role constants + mandatory `make_researcher_headers`/`make_external_client_headers` per-instance builders), `fixtures.py` (clock, single-entity creators, `setup_canonical_stack`, booking lifecycle chain through VALIDATED usage log, billed-entry and priority-award composites, client-side-filter ledger locators), `__init__.py` barrel

**test_suite/** (18 files, `conftest.py` + 17 numbered test files): 115 tests total; all compile, all collect under pytest, no skip/xfail markers.

## Coverage

**Queue A (Difficulty): 27/27 instances covered, 54 tests (exactly 2 per instance), 0 skipped.** Every instance passed the PRD-first filter — the PRD verbatim-covers all 27 (including the three validation-priority pairs, covered by the explicit §2.9 ordered list).

**Queue B (Corner): 61/62 non-stub instances covered (1 test each), 1 skipped, 30 stubs not translated** (all stub `difficulty_instance` cross-references verified to resolve).

Skipped instance:
- `Corner/endpoints/list_filters_combine` — **no PRD coverage**: PRD §2.3 specifies only `limit`/`offset` query params ("List endpoints accept two query parameters"); the `instrument_id`/`status` filter predicates the instance asserts appear nowhere in PRD prose. A PRD-only implementer could ship list endpoints without those filters. Gap left as a gap.

## Notable adjudications (PRD-first two-condition filter)

- **Version numbers asserted relatively** (+1 per mutation via captured versions, e.g. rate-set review loop, all three OCC tests): PRD §2.6 pins "increments by 1 on every mutation" but never the initial value, so literal `version == 6`/`== 2` recipe expectations were translated as per-step increments rather than absolutes.
- **`user_create_defaults_and_envelope`**: kept (status ACTIVE, is_pi false, clock-default created_at instant, envelope meta) but dropped the `department == null` sub-assertion — PRD names a default only for `is_pi`; `department` is "optional" with no stated server-side default (default-value silence pattern). `created_at` asserted as the `2026-08-01T00:00:00` instant (§2.4 clock default + §2.6 three-fractional-digit format) without hard-coding the `Z` suffix rendering.
- **Both preemption instances**: setup reordered so the PRIORITY request is created *before* the STANDARD victim is approved (PRD §3.2 "REQUESTED bookings never block"). The recipe's original order (PRIORITY create over an APPROVED victim) is ambiguous under PRD — §3.6's creation chain states no PRIORITY exception to the overlap check, and §3.6's preemption paragraph is reachable via the reordering under every faithful reading.
- **`authorization_beats_existence_on_batch_finalize`**: second test asserts the same bogus-id call as FinanceOfficer yields `ERR_NOT_FOUND`, pinning the §2.9 ordering claim from both sides.

## Verification performed

- All 115 tests carry exactly one `Design:` tag as the final docstring line; every tag resolves to a real instance in the cited queue (audit script: 0 bad tags).
- All 186 quoted citation segments in docstrings survive whitespace-normalized literal substring match against `PRD.md` (0 failures after fixing two ellipsized quotes).
- No `pytest.mark.skip/skipif/xfail`; no "scaffold"/table references in generated code.
- Two real bugs caught and fixed in review: `_ok()` rejected list-shaped setup responses; `test_07` used `create_approved_booking` without importing it.

## Step 6: Generate Implementation — 2026-08-13T01:12:00.000Z

Done. The implementation is complete and verified.

## Summary

**Files written** (all under `workspace/implementation/`):

- `start.sh` — foreground launcher with guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, reads `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/500 handlers producing the scaffold's error envelope
- `store.py` — in-memory dicts keyed by id (15 entity stores), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, monotonic insertion sequence; **no seeding anywhere** — the store starts empty on every boot
- `errors.py` — all 38 error IDs with exact HTTP statuses from the catalog
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, clamp 1–100), ISO-8601 3-fractional-digit timestamps, Decimal round-half-up money helpers
- `auth.py` — `X-User-ID`/`X-User-Role` validation, 5 roles, entity-backed resolution for Researcher/ExternalClient, role + ownership checks
- `helpers.py` — computed statuses (grant CLOSED>EXPIRED>EXHAUSTED>ACTIVE, award, contract, training expiry), ledger aggregation, buffered half-open vs closed-interval overlap, subsidy waterfall, serializers
- `routes/` — users, instruments, training, grants, ratesets, bookings, usagelogs, billing (batches/entries/fiscal-years), subsidies, ops (contracts/downtime/publications/clock)

**Endpoint count:** 87 (verified against the live app — matches scaffold `endpoint_count: 87`, including `POST /_clock/set_current_utc`).

**State machines:** all 15 implemented with preconditions, side effects, and cascades — user suspension, instrument retire/return-to-service, training certify/re-enroll/revoke with 12-month step-decay (inclusive expiry boundary), grant computed status + close, rate-set DRAFT→UNDER_REVIEW→APPROVED→EFFECTIVE with supersession, booking lifecycle with preemption (all-or-nothing victim selection, created_at DESC / start_at ASC ranking), usage-log correction loop, batch finalize (frozen totals), entry dispute loop with WRITE_OFF compensating ADJUSTMENT + subsidy restoration, subsidy application revision loop, award revoke, contract terminate, downtime confirm/resolve/cancel, publication verify/reject, fiscal-year close with auto-created next period and carryforward re-derivation flagging >5% rate deviations.

**Calculations:** all 10 — usage_charge (provisional and final variants with pinned ceil→floor→round→consumables order), cancellation_penalty (inclusive free-notice boundary), subsidy_offset_waterfall (valid_until ASC/created_at ASC, exact-empty continuation), derived_rate_computation (round-per-line first), break_even_review (projected + actual), fiscal_trueup (accrual official + cash informational), grant_budget_available, preemption_victim_selection, training_expiry, batch_totals. All money in integer cents via Decimal ROUND_HALF_UP.

**Verification:** cold-booted via `bash start.sh` on default port 10000 (ready in ~1s, `0.0.0.0` bound) and on scratch port 18743 across five smoke-test rounds covering CRUD, the full booking→usage→entry→batch→FY-close loop, preemption and ERR_PREEMPTION_BLOCKED, late-cancel/no-show penalties, subsidy waterfall and write-off reversal, OCC (412 on all three endpoints), grant exhaustion/recovery, downtime and suspension cascades, contract overlap half-open boundaries, SoD failures, rate cap (110% boundary + override), break-even waiver flow, force-filtered lists, and pagination envelope — all passing, with state-wipe-on-restart confirmed.

## Step 7: Run Tests and Iterate — 2026-08-13T01:52:00.000Z

All 8 rounds pass 115/115. The benchmark is clean.

## Summary

- **Iterations run:** 3 sweeps (8 parallel rounds each). Sweep 1 surfaced 6 deterministic failures (identical in all 8 rounds). Sweep 2 (post-fix) confirmed the 6 fixes and hit only infrastructure noise (runner's 15s per-test server-restart budget exceeded under multi-pipeline host load; one `ConnectionError` mid-restart — all `error`/transport-level, zero assertion failures). Sweep 3 passed clean: 8/8 rounds × 115/115.

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  1. `test_04_booking_state_machine.py::test_usage_log_create_rejected_while_booking_approved` — dropped `expected_status=422` from the `ERR_BOOKING_NOT_COMPLETED` assertion. PRD §3.8 and §2.9 item 39 name the error_id verbatim, but PRD §5's canonical id-to-status table omits this error entirely (HTTP status is scaffold-only: SCAFFOLD.yaml maps it to 422). Partial-coverage correction: kept the PRD-covered error_id assertion, removed the PRD-silent status pin. (`validate_error`'s registered-map fallback does not contain this error, so no implicit status check remains.)
  2. `test_05_overlap_semantics.py::test_preventive_maintenance_requires_covering_contract` — fixture date bug: the contract was created with `coverage_end=2026-06-30`, which is EXPIRED under the PRD §2.4 default logical clock (2026-08-01), so the PRD-faithful implementation correctly rejected the "covering" branch with `ERR_CONTRACT_REQUIRED`. Moved coverage to 2026-08-01..2026-12-31 (ACTIVE at default clock) and the non-covering event window to 2027-01-15; all three assertion branches (missing contract / non-covering contract / covering contract) preserved.
  3. `test_15_optimistic_concurrency.py::test_occ_booking_reschedule_stale` — the assertion compared `end_at` to the literal input string `"2026-09-01T11:00:00Z"`; PRD §2.6 pins 3-fractional-digit format only for `created_at`/`updated_at`, leaving `start_at`/`end_at` rendering unspecified (two-reader divergence: verbatim echo vs normalized `...:00.000Z`). Changed to compare `after["end_at"] == first["end_at"]` (server-rendered value from the legitimate reschedule), asserting exactly the PRD §2.8 rule — a stale write must not move the window — representation-agnostically, matching the sibling rate-set OCC test's `.startswith(...)` style.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:**
  1. `workspace/implementation/util.py::new_id` — minted ids as `uuid.uuid4().hex` (dashless); PRD §2.6 requires a "server-minted UUID with no type prefix", whose canonical RFC 4122 string rendering (and the benchmark's shared `is_valid_uuid` validator) is the dashed form. Changed to `str(uuid.uuid4())`. This fixed 3 tests (`test_user_create_defaults_and_envelope`, `test_instrument_create_applies_policy_defaults`, `test_grant_computed_fields_zero_at_create`).

- **Feedback notes for generators (no deletions, but two near-miss patterns):** (a) doc-generator should keep every error_id used in §2/§3 present in the §5 status table (ERR_BOOKING_NOT_COMPLETED omission drove a scaffold-only status assertion); (b) unit-test-generator should avoid asserting exact stored string rendering of client-supplied datetimes when PRD only pins the format of server-managed timestamps, and should sanity-check fixture dates against the PRD's declared logical-clock default when computed statuses (EXPIRED) depend on it.

## Step 8: Finalize PRD — 2026-08-13T02:05:00.000Z

Both edits applied and verified. Final diff is exactly two hunks.

## Summary

**Line counts:** PRD.md = 427 lines; PRD_FINALIZED.md = 428 lines (+1 line, +0.23%).

### Changes

- **§2.6 (Common Resource Properties)** — revise — (a) pinned `id` to the canonical hyphenated RFC 4122 string form (five dash-separated hex groups), closing the dashless-hex misreading the original implementer made; (b) extended the three-fractional-digit UTC timestamp rule beyond `created_at`/`updated_at` to every datetime-valued resource field, pinning that client-supplied datetimes are parsed, converted to UTC, and re-rendered canonically (not echoed verbatim), and that date-only fields stay verbatim `YYYY-MM-DD` — `implementation/util.py:17-25`, `util.py:80`, `routes/bookings.py:159-160,409-410`, `routes/usagelogs.py:79-80,153-156`, `routes/subsidies.py:199-200`, `routes/ratesets.py:137,211`, `routes/ops.py:186-187`, `routes/billing.py:136,359`, `routes/training.py:111,113`, `routes/grants.py:72-73,152-156`, `routes/ops.py:86-87`.
- **§5 (Error Code Catalogue)** — insert — added `ERR_BOOKING_NOT_COMPLETED | 400` row (placed between `ERR_SUBSIDY_INELIGIBLE` and `ERR_UNFINALIZED_BATCHES`, mirroring its §2.9 item-39 position) — `implementation/routes/usagelogs.py:74,197` (raised via `fail()`), `implementation/errors.py:13-58` (id absent from `ERROR_STATUS`, so the `fail()` fallback at line 57 yields HTTP 400), `implementation/app.py:32-34` (status passes through unmodified).

### Step-7 diff items needing no PRD edit

- **test fix 2** (maintenance-contract fixture dates): pure fixture bug — PRD §2.4 default clock and §2.4/§3.11 EXPIRED-contract semantics already determine the behavior the implementation exhibits; prose kept verbatim.

### Per-edit pre-edit search log

**Edit 1 — §2.6 UUID clause.**
- (a) Subject: string form of the server-minted resource `id`.
- (b) Paths enumerated: `util.py:17-18` (`new_id`, sole minting site — `grep -rn "uuid\|new_id"` confirms no other), `util.py:77-85` (`new_entity` attaches it to all fifteen entities via every route's create path), and the envelope's `api_request_id` (`util.py:137-143`, `req_`-prefixed, separately pinned in §2.2 — untouched by my wording).
- (c) Adjustment: scoped the clause strictly to the resource `id` field ("with no type prefix, rendered in the canonical RFC 4122 string form") so it makes no claim about `api_request_id`; example UUID verified against the benchmark's `is_valid_uuid` regex.

**Edit 1 (cont.) — §2.6 datetime-rendering clause.**
- (a) Subject: rendering of client-supplied and server-stamped datetime fields.
- (b) Paths enumerated via `grep -rn "fmt_ts\|fmt_clock"` across `routes/` and `helpers.py`: booking create/reschedule (`bookings.py:159-160,409-410`), usage-log create/edit (`usagelogs.py:79-80,153,156`), award minting (`subsidies.py:199-200`), rate-set create/edit (`ratesets.py:137,211`), downtime create (`ops.py:186-187`), server stamps (`training.py:111,113`; `billing.py:136,359`), plus date-only fields stored verbatim (`grants.py:72-73,152-156`; `ops.py:86-87`; `ops.py:333` `published_at`), and the clock test-drive echo (`ops.py:452`, uses `fmt_clock` — whole seconds when microsecond==0).
- (c) Adjustment: scoped the sentence to "datetime-valued field **carried on a resource**" so it makes no claim about the `_clock/set_current_utc` response's `current_utc` (a non-resource payload that omits fractional digits on whole seconds); explicitly listed date-only fields as remaining verbatim `YYYY-MM-DD` to stay consistent with grants/contracts/publications storage.

**Edit 2 — §5 error-table row.**
- (a) Subject: HTTP status for `ERR_BOOKING_NOT_COMPLETED`.
- (b) Paths enumerated: both raise sites (`usagelogs.py:74` create, `usagelogs.py:197` validate) go through `errors.py:fail()`; the id is absent from `ERROR_STATUS` (`errors.py:13-53`), so the fallback at `errors.py:57` yields 400; `app.py:32-34` passes `err.status` through unchanged. A full `grep -rhoE 'fail\("ERR_[A-Z_]+"'` sweep confirmed every other error id used anywhere in the implementation already appears in the §5 table with a matching status, so the added row introduces no inconsistency with any other path.
- (c) Adjustment: none needed — single-row insert, no universal claims; the §5 preamble ("canonical id-to-status mapping only") remains accurate.

## Step 9: Complete PRD — 2026-08-13T02:35:00.000Z

Done. `workspace/PRD_COMPLETED.md` is produced — a minimal inline patch over `PRD_FINALIZED.md` (all edits in-paragraph; no new sections; line count unchanged at 428; +4,649 chars).

**Stats**
- Source: `workspace/PRD_FINALIZED.md` (428 lines / 65,248 chars) → `PRD_COMPLETED.md` (428 lines / 69,897 chars), char-delta +4,649, 26 lines touched.
- Counts: 19 ambiguity-pins, 8 mismatch-revisions (27 changes total).

**Changes** (impl references under `workspace/implementation/`):

- §2.1 — revise — mismatch — "Two of the five roles are opaque" → "Three" (three opaque roles listed) — auth.py:13-15.
- §2.3 — insert — ambiguity — negative `offset` clamps to 0; non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties break by insertion order; `has_more` = `offset` + returned items < `total_count` — util.py:156, 174-206.
- §2.4 — revise — mismatch — clock is *set* (forward or backward), not only advanced; response pinned as 200 with `current_utc`, whole-second times rendered without fractional digits — ops.py:440-452, util.py:28-32.
- §2.8 — revise — mismatch — OCC comparison applies only to integer expected versions (missing/non-integer → `ERR_INVALID_REQUEST` at format validation); on the three OCC endpoints it runs after authn/authz/SoD/path resolution but before body FK existence, state, and format checks; grant-amend `authorized_user_ids` existence verified after formats; rate-set-edit line-instrument existence after the DRAFT state check — bookings.py:368-370, grants.py:116-138, ratesets.py:186-195.
- §2.9 item 5 — revise — mismatch — same OCC carve-out summarized in the priority list.
- §2.9 item 6 — insert — ambiguity — approval requires the EFFECTIVE set to also contain a line for the booking's instrument — bookings.py:224-227.
- §2.9 item 21 — insert — mismatch — action endpoints reject unknown body fields as read, ahead of state legality; exceptions (booking reschedule, usage-log edit, dispute, resolve-dispute, application approval) check state first; rate-set approval ignores the body — e.g. bookings.py:217-219, billing.py:182-191/205-220, subsidies.py:166-180, ratesets.py:266-292.
- §2.9 item 28 — revise — mismatch — preemption feasibility replaces the overlap rule at rule-16 position, ahead of downtime-conflict — bookings.py:238-259.
- §3.1 — insert — ambiguity — suspend only from `ACTIVE`, reactivate only from `SUSPENDED`, else `ERR_INVALID_STATE` — users.py:88-89, 109-110.
- §3.2 — insert — ambiguity — downtime-conflict comparison uses the booking's raw unbuffered window — helpers.py:178-180.
- §3.2 — insert — ambiguity — return-to-service only from `DOWN`/`MAINTENANCE`; blocking CONFIRMED window or other status → `ERR_INVALID_STATE`; re-retiring `RETIRED` → `ERR_INVALID_STATE` — instruments.py:92-93, 133-142.
- §3.3 — insert — ambiguity — certifying for a `RETIRED` instrument → `ERR_INVALID_STATE` — training.py:106-108.
- §3.4 — revise — mismatch — grant close releases no encumbrance (keeps counting until bookings complete/cancel); charging a `CLOSED` grant fails `ERR_GRANT_INACTIVE` at creation and approval — grants.py:164-178, helpers.py:105-117.
- §3.5 — insert — ambiguity — replacing `lines` on edit resets verdicts and `flagged_for_review` flags — ratesets.py:213-216.
- §3.5 — revise+insert — ambiguity — cap bypass requires a non-empty `override_justification` string; submit pins: empty `lines` or RETIRED instrument → `ERR_INVALID_REQUEST`, missing instrument → `ERR_NOT_FOUND` — ratesets.py:235-258.
- §3.5 — insert — ambiguity — activation: before `effective_from` → `ERR_INVALID_STATE`; missing FY period → `ERR_FY_CLOSED` — ratesets.py:324-331.
- §3.5 — insert — ambiguity — break-even diagnostic: per-line `projected_revenue_cents`/`projected_cost_cents`/`suggested_internal_rate_cents_per_hour` (carryforward 0 when period missing); stored verdicts (incl. `WAIVED`) once submitted, live while `DRAFT`; `overall_verdict` `DEFICIT` iff any line's reported verdict is `DEFICIT` — ratesets.py:347-377.
- §3.6 — revise — ambiguity — approval's rate-set gate also requires a line for the instrument — bookings.py:224-227.
- §3.6 — insert — mismatch — preemption feasibility evaluated at the overlap position, ahead of downtime re-check — bookings.py:238-253.
- §3.7 — insert — ambiguity — actor-driven cancels record `penalty_waived` false — bookings.py:349.
- §3.7 — insert — ambiguity — reschedule overlap check exempts STANDARD APPROVED occupants for PRIORITY bookings; no preemption on reschedule — bookings.py:388-390.
- §3.7 — insert — ambiguity — check-in window inclusive at both ends — bookings.py:433-435.
- §3.9 — revise — ambiguity — batch creation: FY period must exist and be `OPEN`, missing → `ERR_FY_CLOSED` — billing.py:57-62.
- §3.10 — revise+insert — ambiguity — application creation itself enforces INTERNAL affiliation (`ERR_SUBSIDY_INELIGIBLE`); `reviewed_by` refreshed on every FinanceOfficer review action — subsidies.py:58-61, 137, 155, 207, 225.
- §3.10 — insert — ambiguity — award approval requires `valid_until` strictly after `valid_from` (`ERR_INVALID_REQUEST`); approve response carries the minted `SubsidyAward` — subsidies.py:183-184, 209.
- §3.11 — insert — ambiguity — preventive-maintenance contract containment judged on event start/end calendar dates — ops.py:156-165.
- §3.13 — revise — ambiguity — close cascade re-derives against the next-year period's `carryforward_in_cents` (pre-existing value when the period already exists); deviation threshold = 5% of |suggested| (zero suggestion flags any non-zero stored rate); cascade-set flags never cleared — billing.py:362-399.

Notes: tests were treated as non-authoritative per instructions. The `expires_at_dt` internal field leaks into TrainingRecord serialization (helpers.py `expires_at_dt` lacks the underscore prefix stripped by `_public`); the subagent deliberately did not pin that impl wart.

Pipeline complete: all Steps 1–9 done; final stability sweep 8/8 rounds × 115/115 tests passing.

## Orchestrator close-out — 2026-08-13T02:40:00.000Z

Resume run completed: kept Step 2 scaffold artifacts from the killed run (validated YAML, complete tails), regenerated everything downstream. Verified final results.*.json directly (flat schema, no `summary` key): all 8 rounds passed=115/115, failed=0, errors=0. All pipeline artifacts present; no writes outside this directory.
