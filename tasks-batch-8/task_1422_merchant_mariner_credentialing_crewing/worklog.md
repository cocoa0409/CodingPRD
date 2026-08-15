# Worklog — task_1422_merchant_mariner_credentialing_crewing

## Step 1: Create Task Directory — 2026-08-13T05:52:00.000Z

Task directory `tasks/task_1422_merchant_mariner_credentialing_crewing/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T07:25:00.000Z

Scaffold generation complete for `task_1422_merchant_mariner_credentialing_crewing`, with `scaffold_lint.py` verdict: **clean lint** (1061 test-recipe calls across §1.8/§1.9 all conform to §1.5; all §1.1 FKs reverse-reachable).

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/SCAFFOLD.yaml` — 2065 lines (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1066 lines (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/SCAFFOLD_CORNER_DESIGN.yaml` — 1398 lines (single top key `scaffold_corner_design`)

**Counts**
- Entities: **15** (Mariner, Vessel, ManningSlot, CrewRotationPlan, Credential, SeaServiceRecord, MedicalCertificate, DrugTestRecord, TrainingCourse, TrainingEnrollment, TrainingBudget, UnionHall, UnionRegistration, Assignment, TravelBooking) — top of the Expert band, graph topology with a self-referential credential prerequisite chain and cross-aggregate relief pairing
- Endpoints: **93** (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` and `GET /_clock/current`)
- State machines: **15** blocks (13 entities; Assignment carries 3 parallel dimensions: lifecycle × travel × repatriation); Credential is deeply cyclic (renewal/deny/expire/late-renew loops + SUSPENDED_PREREQ cascade edges)
- Calculations: **9** (dual-variant sea-service day credit, threshold upgrade eligibility, tiered reimbursement, per-leg-rounding travel fares, evaluation-order-pinned readiness posture, manning compliance, clock expiry sweep, dual-semantics overlap checks, drug currency window)
- Also: 3 OCC concurrency rules, 15 ordered validation rows, 60 error codes, 6 roles (segregation-of-duties model; UnionDispatcher/Mariner entity-backed)
- §1.8 instances: **25** (dual_variant 2, combinatorial 3 across modes a/b/c, non_linear 3, transitive_cascade 3 incl. a depth-4 clock cascade, priority_conflict 3 distinct pairs, boundary 3 distinct metrics/endpoints, cross_entity 3 distinct pairs, overlap 2 distinct interval semantics, invariant 3 distinct conserved quantities)
- §1.9 instances: **77** (64 active across all nine guide sections + 13 `excluded_because` stubs citing §1.8 instances)

**Key design decisions**
- All computed literals in asserts were pre-executed (e.g., sea-service 360-day leap-year boundary 2024-01-01→2024-12-25; per-leg fare rounding 11538+11538=23076 vs 23077 sum-first; reimbursement min-nesting 160000/180000/144000; cancel fee round_half_up(10500×0.15)=1575)
- Every setup chain replays from empty DB using only §1.5 endpoints; OCC payloads use `${var}` captures exclusively; placeholder closure and stub-reference integrity were mechanically re-verified beyond the lint (zero unbound `${var}`, all 13 stubs resolve to real §1.8 names)
- One repair during generation: removed unreachable `ERR_MEDICAL_CERT_EXPIRED` (clock sweep makes a past-expiry SUSPENDED cert unobservable), added missing `ERR_RANK_BELOW_MINIMUM` to the catalog/validations, and materialized Credential→SUSPENDED_PREREQ as first-class system transitions for enum closure.

## Step 3: Copy Shared Files — 2026-08-13T07:26:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T07:52:00.000Z

All checks pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/PRD.md` — 412 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC & header contract (6 roles, identity semantics per role, scoping rules), 2.2 API Response Structure (byte-identical verbatim block), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), 2.4 Common Resource Properties, 2.5 Request Validation Pipeline (15-step priority ordering), 2.6 Logical Clock & Expiry Sweep (default `2026-08-01T00:00:00Z`, pinned 7-step sweep), 2.7 Precision (integer cents round-half-up, half-day floor grid, second-precision inclusive boundaries), 2.8 OCC (3 rules), 2.9 Derived Postures & Cascading Consistency (pre-transition snapshot rule)
- §3 Business Logic (9 subsections): 3.1 Mariner Registration & Lifecycle, 3.2 Readiness Posture gates, 3.3 Credentials & Prerequisite Chains, 3.4 Sea Service & Upgrade Eligibility, 3.5 Medical & Drug-Test Program, 3.6 Vessels/Safe Manning/Rotation Plans, 3.7 Crew Assignment & Dispatch Channels, 3.8 Travel & Repatriation, 3.9 Training/Budgets/Reimbursement
- §4 Endpoint Definitions — 93 rows, 4 columns each
- §5 Error Code Catalogue — 60 rows, 2 columns; document ends there (no audit footer)

**Coverage audit (all PASS):**
- **Contract 1 — Field-Name Coverage:** 101/101 `entities[].fields` names, 77/77 endpoint input identifiers, 20/20 query params, 9/9 path params — all present in backticks (two FK fields `course_id`/`hall_id` were caught missing in pass 1 and repaired in pass 2).
- **Contract 2 — Rule Coverage:** 15/15 validation priorities expressed as an ordered pipeline with first-match-wins semantics (incl. intra-step-13 ordering: rotation window → mariner overlap → slot handover); 3/3 OCC rules with `write_endpoint` + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; all state-machine transitions expressed (the single checker flag, Mariner `ACTIVE`/`SUSPENDED` → `TERMINATED`, was a false positive — both source states, the `ERR_ACTIVE_CREW_ABOARD` precondition, and all cascades are in one passage); 35/35 precondition error IDs matchable in prose; all 9 calculations expressed as reconstruction-safe prose with constants embedded (200,000¢ cap, 80%/100% channel pct, 15% cancellation fee, 365-day drug currency, 180-day lapse grace, 30-day restricted window, 360/270-day and grade 4/6 upgrade thresholds, 1.0/0.5 region factors, 1.5× twelve-hour multiplier, half-day floor, per-leg-then-sum pinned rounding); all endpoint `side_effects`/`applies_to` scopes covered (readiness gates per endpoint, endorsement chain, channel rules, SoD pairs); sibling branches rendered with equal density (VALID/EXPIRED renewal paths, QUOTED/BOOKED vs TICKETED cancel fees, resume branching on `actual_sign_on_at`, ACTIVE vs LAID_UP decommission preconditions, provisional vs verified day-credit variants with worked examples).
- **Contract 3 — §3 Path Purity:** 905 backtick tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos.
- **Structural:** §2.2 verified byte-identical to `section-2.2-response-structure.md`; §4 table strictly 4 columns; §5 strictly 2 columns; all 60 scaffold error IDs and all 93 endpoint paths present.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate Unit Tests — 2026-08-13T08:52:00.000Z

All checks pass. Generation is complete.

## Summary

### Files written

**`test_helpers/`** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/test_helpers/`):
- `types.py` — 15 entity TypedDicts + 17 status/role enums (all entities carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with ~70 methods covering every PRD §4 endpoint
- `api_errors.py` — full 64-entry `ApiErrorId` enum + HTTP status map, registered with the framework via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + seat-ledger and budget invariants
- `factories.py` — payload factories with uuid-unique codes (MRN/IMO/course/local_number)
- `constants.py` — thresholds (200000-cent course cap, 0.80/1.00 channel pcts, 365-day drug currency, 30-day restricted window, 180-day lapse grace, 15% ticketed-cancel fee, pinned default clock)
- `test_users.py` — shared opaque-role headers + `make_mariner_headers`/`make_union_dispatcher_headers` entity-backed builders
- `fixtures.py` — composite fixtures: activated mariners, vessel+slot+plan environments, PROPOSED/CONFIRMED/ONBOARD assignments, relief pairs, enrolled enrollments, union registrations, clock control
- `__init__.py` — barrel export

**`test_suite/`** (11 files, 114 tests): `conftest.py` + `test_01` registry/validation (8), `test_02` readiness/clock (7), `test_03` credentials (8), `test_04` sea service/upgrades (11), `test_05` drug/medical/activation (5), `test_06` vessel manning/rotation/OCC (13), `test_07` assignment gates/overlaps (15), `test_08` lifecycle/travel (13), `test_09` training/budget (19), `test_10` security/RBAC/pipeline (15).

### Test counts per queue
- **Queue A (Difficulty): 50 tests — 25/25 instances covered with exactly ≥2 tests each**
- **Queue B (Corner): 64 tests — 63/64 non-stub instances covered** (one instance has 2 tests: `restricted_window_exactly_30_days` split into 30-days/31-days sides); 13 `excluded_because:` stubs not translated, all cross-references verified to resolve.

### Skipped instances
- **`Corner/calculations/drug_currency_inclusive_boundary`** — fails the PRD-first filter (condition 2, unique derivability): the instance asserts posture `CLEAR` at the exact drug-currency boundary instant, but PRD §3.2 uniquely derives `RESTRICTED` there — `drug_test_current_until` equals now, so it is the earliest expiry and falls "within 30 days of now". The instance's asserted outcome contradicts the PRD, so the instance was skipped per spec (gap logged, not weakened). The one-second-later `BLOCKED`/`DRUG_CURRENCY_LAPSED` behavior is incidentally exercised by `medical_expiry_instant_boundary`'s analogous pattern.

### Stage 2 self-audit result
- Every test carries exactly one `Design:` tag; all 114 tags resolve to real instances in the correct queue/section; no stub is tagged; no stub cross-reference is broken.
- Verbatim-citation pass: every docstring's quoted PRD text contains a ≥8-word substring surviving literal (whitespace-normalized) grep of `PRD.md` — 0 failures.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings.
- All asserted `error_id`s are named in PRD §2/§3 prose and present in the registered HTTP status map; all helper imports resolve; all modules compile and import cleanly.
- OCC tests use captured-version-relative assertions (create-response version + 1) rather than hard-coded literals, since PRD §2.4 pins the increment but not the initial value.

## Step 6: Generate Implementation — 2026-08-13T08:53:00.000Z

All 93 registered routes match the scaffold's endpoint table exactly, and all 170 smoke checks pass. The work is complete.

## Summary

**Task**: Generated a complete Python + Flask implementation of the Merchant Mariner Credentialing & Crewing API in `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/implementation/`.

**Files written** (18 files, ~4,300 lines):
- `start.sh` — guarded dependency install (`pip install` only when flask is missing) + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — flask>=3.0
- `app.py` — app factory, blueprint registration, per-request global lock (cascade atomicity), error handlers
- `db.py` — in-memory store (15 entity dicts, empty at boot, zero seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, ISO-8601 parse/format with 3 fractional digits
- `errors.py` — `ApiError` + the full 59-entry error catalog with exact HTTP statuses
- `response.py` — envelope: `{meta: {api_request_id, api_request_timestamp, ...pagination}, response_type, data}`; error shape `{...meta, response_type: "error", data: {error_id, message}}`
- `helpers.py` — `X-User-ID`/`X-User-Role` auth (pipeline steps 1-2), Mariner/UnionDispatcher scoping (step 3), body validators, `limit`/`offset` pagination (default 10, min 1, max 100)
- `serialize.py` — 15 entity serializers with computed fields (`seats_open`, `available_cents`, coverage, postures)
- `services.py` — all calculation rules: 5-gate readiness posture with restricted-window reasons, manning compliance posture, the 7-step pinned expiry sweep (expire → lapse at 180d → prereq cascade → medical expiry → posture recompute → BLOCKED assignment suspension → vessel recompute), sea-service day credit (exact `Fraction` math, half-day floor), upgrade eligibility (calendar-month lookback), training reimbursement (`min(cost, 200000) × channel_pct`, Decimal ROUND_HALF_UP), travel fares (per-leg round-half-up then sum; 15% cancel fee), overlap checks (half-open mariner double-booking; bounded whole-day slot handover)
- 9 route modules: `routes_mariners.py`, `routes_credentials.py`, `routes_sea_service.py`, `routes_medical.py`, `routes_vessels.py`, `routes_assignments.py`, `routes_training.py`, `routes_union.py`, `routes_clock.py`

**Endpoint count**: 93 routes registered — exactly matching the scaffold's 93-endpoint table.

**Key design decisions**:
- Validation follows the PRD §2.5 15-step pipeline literally (schema before OCC before SoD before state before readiness/endorsement/channel/temporal/aggregate/fiscal gates), so coexisting violations surface the correct error.
- Version/`updated_at` bump only when a persisted field actually changes, including recomputed derived fields and cascade-touched children; one bump per resource per mutation event.
- Posture flips to BLOCKED suspend both CONFIRMED and ONBOARD assignments (PRD §3.7 prose wins over the scaffold's CONFIRMED-only phrasing on the mariner-suspend transition).
- `total_fare_cents` stays null until ticketing; `cancellation_fee_cents` stays null until cancellation (0 from QUOTED/BOOKED, 15% half-up from TICKETED).
- Activation drug-test gate accepts any COMPLETED NEGATIVE within 365 days (PRD §3.1 has no type filter), while posture gate 3 restricts to the four qualifying types.
- Scoping: Mariner role is 403-scoped on `/mariners/{id}` subtrees and single-resource GETs of mariner-linked resources; UnionDispatcher is 403-scoped on own-hall mutations and own-hall UNION_DISPATCH assignment confirm/cancel; flat list GETs remain open per the "all GET endpoints" RBAC rows.

**Verification**: three ad-hoc suites (88 + 62 + 20 = 170 checks) all pass, covering the full assignment/travel/training/union/credential lifecycles, sweep cascades, OCC 412s, SoD 403s, boundary semantics (half-open overlap, 3-day handover equality, expiry == now still valid), and 402 budget gate. `start.sh` was launched exactly as the evaluator runs it (`bash start.sh`), and kill/relaunch confirmed a clean empty store and default clock on every boot.

## Step 7: Run Tests and Iterate — 2026-08-13T09:12:00.000Z

All 8 rounds pass 114/114. The sweep is clean.

**Summary**

- **Iterations run:** 2 (initial 8-round sweep → diagnosis + fix → confirming 8-round sweep, all 8 rounds at 114/114 passed).

- **Tests deleted:** none. All 6 failing tests asserted PRD-verbatim rules:
  - `test_immediate_clock_visibility_after_set` — PRD §2.6: "the clock reads exactly 2026-08-01T00:00:00Z" (exact-string, uniquely derivable).
  - `test_renewal_deny_loops_back_to_valid_with_old_dates` / `test_renewal_approve_then_late_renewal_after_expiry_sweep` — PRD §3.3: deny "keeps the old dates unchanged"; approve "replaces `issue_date` with `new_issue_date` and `expiry_date` with `new_expiry_date`" (echo semantics).
  - `test_positive_result_blocks_posture_without_extending_currency` — PRD §3.2/§3.5: `drug_test_current_until` = latest qualifying NEGATIVE `collected_date` + 365 days.
  - `test_union_dispatch_blocked_by_stale_dues_then_allowed` — PRD §3.7: "`dues_current_until` initialized to the `seniority_date`".
  - `test_sign_on_temporal_then_travel_gate_ladder` — PRD §3.7: "Sign-on stamps `actual_sign_on_at` with the current clock".
  Unique derivability holds because PRD §2.4 scopes three-fractional-digit formatting to `created_at`/`updated_at` only, and §2.7 pins second precision for datetimes; no PRD sentence sanctions `.000Z` on domain datetime fields.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/` (one root cause — domain datetimes serialized with `.000Z` instead of second-precision PRD form):**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/implementation/db.py` — added `fmt_dt_sec()` (`%Y-%m-%dT%H:%M:%SZ`) alongside the existing millisecond `fmt_dt()`; `now_iso()` unchanged so `created_at`/`updated_at`/`api_request_timestamp` keep the three-fractional-digit format required by PRD §2.2/§2.4.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/implementation/serialize.py` — all domain datetime fields (`expiry_date`, `issue_date`, `start_date`/`end_date`, `scheduled_date`/`collected_date`, `seniority_date`/`dues_current_until`, `sign_on_date`/`planned_relief_date`/`actual_sign_on_at`/`actual_relieved_at`, leg `depart_at`/`arrive_at`, `drug_test_current_until`, plan `effective_from`/`effective_to`) now serialize via `fmt_dt_sec`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/implementation/routes_clock.py` — `current_utc` (both set and get) now formatted via `fmt_dt_sec`, satisfying "reads exactly 2026-08-01T00:00:00Z".
  - `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/implementation/routes_mariners.py` — upgrade-eligibility `window_start` now formatted via `fmt_dt_sec`.

No PRD-required check was removed or weakened; no test was skipped, relaxed, or deleted; storage remains in-memory only with empty boot state.

## Step 8: Finalize PRD — 2026-08-13T09:20:00.000Z

Done. `PRD_FINALIZED.md` created at `/home/ubuntu/github/CodingPRD/tasks/task_1422_merchant_mariner_credentialing_crewing/workspace/PRD_FINALIZED.md` with exactly one edit.

## Summary

**Line counts / delta:** PRD.md = 412 lines, PRD_FINALIZED.md = 412 lines (edit is intra-paragraph); +833 characters, +1.2%.

**Changes (one total):**
- §2.7 — insert — appended a sentence pinning that every datetime value the API returns is rendered at whole-second precision (`YYYY-MM-DDTHH:MM:SSZ`), explicitly covering all domain datetime fields (`issue_date`/`expiry_date`, `start_date`/`end_date`, `scheduled_date`/`collected_date`, `seniority_date`/`dues_current_until`, `sign_on_date`/`planned_relief_date`/`actual_sign_on_at`/`actual_relieved_at`, leg `depart_at`/`arrive_at`, `drug_test_current_until`, plan `effective_from`/`effective_to`), the clock's `current_utc`, and computed-read fields such as `window_start`, while reserving the three-fractional-digit form for `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2) — `implementation/db.py:40-51`, `implementation/serialize.py:3` + all 19 field sites, `implementation/routes_clock.py:29,35`, `implementation/routes_mariners.py:316`.

**Why only one edit:** All four step_7_diff implementation fixes share a single root cause — domain datetimes were rendered `.000Z` instead of second-precision. The six failing tests asserted PRD-verbatim rules (§2.6 exact clock string; §3.3 renewal echo semantics; §3.2/§3.5 `drug_test_current_until` computation; §3.7 dues init and sign-on stamping) that remain true verbatim against the fixed implementation, so no other PRD prose needed revision. The one genuine gap was that no PRD sentence explicitly stated the *rendering* format of domain datetime fields — demonstrably mis-readable, since the original implementation got it wrong.

**Per-edit pre-edit search log:**
- Edit 1 (§2.7 sentence):
  - (a) Subject: serialization precision/format of datetime values in API responses.
  - (b) Paths enumerated: `grep -rn "fmt_dt|strftime|isoformat|now_iso"` across all impl `.py` — db.py:22,28-51,75-76,89,96 (`parse_dt`, `fmt_dt`, `fmt_dt_sec`, `now_iso`→`created_at`/`updated_at`); response.py:19,31 (`api_request_timestamp` via `now_iso`, success + error envelopes); serialize.py:3,30,78-79,96-97,116-117,135-136,150-151,168-169,234-236,253-257,271-272 (every domain datetime field); routes_clock.py:5,29,35 (`current_utc`, set + get); routes_mariners.py:7,316 (`window_start`). Verified no other render path exists: sea-service-summary returns numerics only (routes_mariners.py:320+), manning-compliance returns ids/counts only (routes_vessels.py:236-262), and all domain datetimes are stored as parsed datetimes via `req_dt` (helpers.py:146-159), so nothing echoes raw client strings.
  - (c) Wording adjustment: chose a universal claim ("every datetime value the API returns") with a "for example" field list instead of a closed enumeration so no off-site field is excluded; explicitly carved out `created_at`/`updated_at`/`api_request_timestamp` to stay consistent with §2.2/§2.4; anchored the example to §2.6's exact clock string; left the existing comparisons sentence untouched (comparison internals are outside the step_7_diff scope).

## Step 9: Complete PRD — 2026-08-13T09:52:00.000Z

The patch is complete and verified. Final report:

## Summary

**Source:** `workspace/PRD_FINALIZED.md` (412 lines / 70,259 chars) → `workspace/PRD_COMPLETED.md` (414 lines / 74,898 chars), char-delta **+4,639**. Only `PRD_COMPLETED.md` was edited; 22 hunks total.

**Counts:** 17 ambiguity-pins, 5 mismatch-revisions.

### Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)

- §2.1 — insert — ambiguity — Mariner self-scope is enforced on the `/mariners/{id}` subtree and mariner-linked single-resource fetches/actions only; flat listings (`GET /mariners`, `/credentials`, `/assignments`, per-vessel sea-service list) carry no mariner scoping — implementation/routes_mariners.py:117, routes_credentials.py:127, routes_assignments.py:286, routes_sea_service.py:133
- §2.3 — insert — ambiguity — `created_at` sort ties broken by creation order; non-integer/out-of-range `limit`/`offset` (and integer query filters like `fiscal_year`) → `ERR_INVALID_REQUEST` — implementation/helpers.py:199-233, routes_training.py:461-466
- §2.4 — insert — ambiguity — all server-stamped timestamps (`created_at`, `updated_at`, envelope `api_request_timestamp`) read the logical clock, never wall-clock — implementation/db.py:85-96, response.py:19,31
- §2.5 step 3 — insert — ambiguity — on assignment proposals the own-hall dispatcher check reads the body-supplied registration, so FK resolution precedes it: dangling `union_registration_id` → `ERR_UNION_REGISTRATION_NOT_FOUND`; dispatcher proposing UNION_DISPATCH with no/other-hall registration → `ERR_FORBIDDEN_RESOURCE_ACCESS` ahead of the schema required-field check — implementation/routes_assignments.py:198-219,234-238
- §2.5 step 5 — revise — mismatch — added `vessel_id` (sea-service entry) to the body-FK list — implementation/routes_sea_service.py:63-67
- §2.6 — insert — ambiguity — clock may be set to any instant (no monotonicity constraint); the set call returns the post-sweep `current_utc` — implementation/routes_clock.py:24-29
- §2.6 item 5 — revise — mismatch — sweep recomputes *every* mariner's posture (clock drift alone can flip postures), not only "affected" mariners — implementation/services.py:297-301
- §2.7 — revise — mismatch — datetime comparisons evaluate the parsed instants exactly as supplied (second precision in practice), replacing the absolute "evaluated at second precision" claim — implementation/db.py:15-25 (full-precision comparison), db.py:40-51 (second-precision rendering)
- §2.9 — insert — mismatch — decommission is the lone exception to immediate recompute: it retires billets without recomputing the vessel's stored posture fields — implementation/routes_vessels.py:203-233 (no `recompute_vessel` call)
- §3.1 — insert — ambiguity — `annual_training_cap_cents` is a non-negative integer — implementation/routes_mariners.py:87
- §3.1 — insert — ambiguity — activation/reinstatement drug gate accepts any `test_type`, including `REASONABLE_CAUSE` — implementation/routes_mariners.py:61-68
- §3.1 — insert — ambiguity — profile edit: null-valued fields treated as omitted; every accepted edit bumps `version` even when values are unchanged — implementation/routes_mariners.py:150-194
- §3.2 — insert — ambiguity — gate-4 latest-test tie-break extended: after `created_at`, remaining ties broken by creation order (later-created wins) — implementation/services.py:122-125
- §3.2 — insert — ambiguity — with several simultaneously valid medical certificates (or valid primary credentials), the source's expiry is the latest among the satisfying rows — implementation/services.py:106,137
- §3.2 — insert — ambiguity — the 30-day restricted window is inclusive: an expiry exactly 30 days after now counts as within — implementation/services.py:146-153
- §3.4 — insert — ambiguity — `by_track` shape pinned: array of `{rank_track, provisional_days, verified_days}`, one per track present on counted records, sorted by `rank_track` — implementation/routes_mariners.py:329-351
- §3.4 — insert — ambiguity — upgrade lookback: `start_date` on or after `window_start` qualifies; calendar-month subtraction clamps the day to month-end — implementation/services.py:343-362
- §3.5 — revise — mismatch — medical reinstatement allowed whenever the certificate has not expired at the current clock (expiry on or after now), not strictly "in the future" — implementation/routes_medical.py:136-147 (no expiry re-check; sweep invariant)
- §3.6 — insert — ambiguity — defining a billet on a vessel not `REGISTERED`/`ACTIVE` → `ERR_VESSEL_NOT_ACTIVE`; billets listed per vessel filterable by `status` — implementation/routes_vessels.py:283-287,310-312
- §3.6 — insert — ambiguity — billet revision: null-valued fields treated as omitted; every accepted revision bumps `version` even when unchanged — implementation/routes_vessels.py:334-385
- §3.6 — insert — ambiguity — mark-underway from `DEFICIENT` with missing/empty waiver → `ERR_VESSEL_NOT_COMPLIANT` (error id previously named only for `CRITICAL_SHORTAGE`) — implementation/routes_vessels.py:147-156
- §3.6 — insert — ambiguity — rotation plan: `effective_to` must be strictly later than `effective_from` (`ERR_INVALID_REQUEST`); `max_handover_overlap_days` is a non-negative integer — implementation/routes_vessels.py:423-428
- §3.6 — insert — mismatch — decommission leaves stored `compliance_posture`/`slots_total`/`slots_covered` unrecomputed; the manning-compliance read recomputes and persists on every call while the single-vessel fetch returns stored values — implementation/routes_vessels.py:203-264 (decommission lacks recompute; manning_compliance:240 recomputes; get_vessel:115 does not)
- §3.7 — insert — ambiguity — `union_registration_id` supplied on a `DIRECT_HIRE` proposal is validated and stored but inert in channel checks — implementation/routes_assignments.py:198-205,243
- §3.8 — insert — ambiguity — `legs` missing/non-array → `ERR_INVALID_REQUEST`, empty array → `ERR_NO_TRAVEL_LEGS`; leg replacement may set an empty array and is not conditioned on assignment status — implementation/routes_assignments.py:515-524,563-574
- §3.9 — insert — ambiguity — `receipt_amount_cents` is a required non-negative integer — implementation/routes_training.py:396

### Notable non-changes (verified already pinned)
The pipeline error-precedence order, per-leg round-half-up fare computation, provisional-amount cap/percentage order, overlap and handover formulas (including equality-allowed handover and half-open mariner overlap), the seven-step sweep order, OCC field names and 412 status, terminal-state sets, and all endpoint role assignments matched the implementation exactly and were left untouched. The §3.1 manual-suspend cascade mentioning only `CONFIRMED` assignments was left as-is because §3.7 already pins the ONBOARD leg for any posture flip to `BLOCKED`, "through manual suspension" included.
