# Worklog — task_1162_emergency_board_up_property_securing

## Step 1: Create Task Directory — 2026-08-11T06:05:00.000Z

Task directory pre-assigned by caller: `tasks/task_1162_emergency_board_up_property_securing` with `workspace/` subdirectory. Auto-index scan skipped per instructions. Verified both directories exist on disk.

## Step 2: Generate Scaffold — 2026-08-11T07:19:00.000Z

Scaffold generation complete for task 1162. All three artifacts are written and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing/`):
- `SCAFFOLD.yaml` — 1505 lines (§1.0–§1.7 + concurrency rules; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2024 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3197 lines (single top key `scaffold_corner_design`)

**Counts**
- Entities: 14 (Market, Subcontractor, Coverage, Customer, Property, Job, Assignment, SafetyAssessment, ScopeItem, TemporaryService, PatrolVisit, PermitCase, DocumentPackage, Invoice)
- State machines: 10 (Job cyclic w/ breach loop + repair-verification revert; Assignment fork w/ auto re-offer; SafetyAssessment score-forked; ScopeItem; TemporaryService ACTIVE↔PAUSED; PatrolVisit; PermitCase branching + auto-expiry; DocumentPackage LOCKED↔AMENDED cycle; Invoice DISPUTED↔SUBMITTED cycle; Subcontractor ACTIVE↔SUSPENDED)
- Calculations: 9 (incl. 2 dual-variant entries on different domains: invoice provisional/final vs subcontractor lenient/strict reliability)
- Endpoints: 55 (incl. `POST /_clock/set_current_utc` with the mandated default 2026-05-01T00:00:00Z)
- Errors: 37 — every one referenced by at least one design instance
- Roles: 5 (PlatformAdmin, Dispatcher opaque; Customer, Subcontractor entity-backed; Anonymous marker for negative auth tests)
- §1.8 difficulty instances: 19 (each of the 9 rules ≥2; combinatorial_formula has 3 covering modes a, b, c)
- §1.9 corner instances: 51 active + 8 `excluded_because` stubs (across all 9 taxonomy sections)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1052 calls scanned)

**Design decisions worth recording**
- Archetype: workflow orchestration + compliance/audit; graph topology (M2M Coverage junction, cross-aggregate gating); role model segregation-of-duties (assessor ≠ assignee subcontractor, enforced via entity-backed `X-User-ID`).
- "Harder than expert" was achieved via density, not volume: dual-variant invoice math with a pinned 8-step evaluation order resolving a tier/discount circularity (falsifiable at 205000 → 194750), per-visit-then-sum patrol rounding (28122 vs 28121 off-by-one-cent), depth-3 patrol-miss cascade (visit→service→job→sibling services), suspension cascade (sub→assignments→jobs), two OCC rules on repeatable creates (scope items, package artifacts).
- Fixed during self-review: (1) dropped `ERR_JOB_HAS_OPEN_ASSIGNMENT` — replay proved INTAKE-with-open-assignment is unreachable, so the error was dead code; re-dispatch of a non-INTAKE job is `ERR_INVALID_STATE`. (2) Widened the invoice-submit documentation gate from `COMPLETE` to `{COMPLETE, LOCKED, AMENDED}` — otherwise a package locked by the provisional submission would have permanently blocked FINAL submission. (3) Offer expiry is lazy (evaluated on respond/withdraw), while the clock endpoint deterministically sweeps only notification deadlines.
- All numeric asserts in both design files were hand-computed from the declared formulas/constants (sheet ceil math, tarp 1.25 overlap, tiered discount, reliability ratios 0.6667/0.5, billable-day ceilings, 120% variance cap).

## Step 3: Copy Shared Files — 2026-08-11T07:20:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1162_emergency_board_up_property_securing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T07:33:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing/workspace/PRD.md` — 322 lines. The withheld difficulty/corner index files were never opened.

## Section list

- **§1 Introduction** (2 paragraphs, business-context angle)
- **§2 Global Specifications** — 2.1 Roles, Identity, and Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Nested Resource Retrieval · 2.7 Validation Order of Precedence (10-stage ladder) · 2.8 Money, Quantities, and Rounding · 2.9 Optimistic Concurrency Control · 2.10 Cross-Resource Consistency and Automatic Transitions
- **§3 Business Logic & Workflows** (9 subsections, timeline grouping) — 3.1 Network building (markets/subcontractors/coverage/customers/properties) · 3.2 Intake, Dispatch, and the Offer Cycle · 3.3 Crew Arrival and SLA Evaluation · 3.4 Safety Assessment · 3.5 Scope & Materials (incl. complete-securing gates) · 3.6 Temporary Services, Patrols, Breach Cascade · 3.7 Permits & Notifications · 3.8 Documentation & Invoicing · 3.9 Verification, Removal, Closure
- **§4 Endpoint Definitions** — 55 rows, 4 columns (matches scaffold endpoint count)
- **§5 Error Code Catalogue** — 37 rows, 2 columns

## Hard Contract results

- **Contract 1 (Field-Name Coverage): PASS** — 112 required identifiers (entity fields + endpoint inputs + query params), 112 present in backticks, 0 missing. One gap found and fixed during audit (`temporary_service_id`).
- **Contract 2 (Rule Coverage): PASS** — all 10 validation priorities expressed as an explicit ordered ladder with stage-6 sub-order; both OCC rules named with write-endpoint + `expected_job_version`/`expected_package_version` + `ERR_STALE_VERSION`/412; all state-machine transitions, all 9 calculation formulas (constants 144/32/1.25, hazard weights 45/25/20/15/10, thresholds 70/30 inclusive, multipliers 1.50/1.25/1.00, tiers 200,000/500,000 cents, variance cap 120%, 30-min offer expiry, 86,400-second billing day), all error-condition pairings, and all endpoint side effects appear in prose. One genuine gap found in self-audit — the `ON_SITE → SECURED` complete-securing transition with its four gates and counter side effects — fixed by adding a dedicated §3.5 paragraph.
- **Contract 3 (§3 Path Purity): PASS** — 543 backtick tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path combos.

## Zero-Silence Rule self-audit

No scaffold rule was left inexpressible. Two faithful silences worth noting: the scaffold attaches no error id to (a) scope-add-after-SECURED, temporary-service-on-non-SECURED, and package-before-SECURED eligibility, and (b) window well-formedness (`window_end` after `window_start`, `ends_at` after `starts_at`). The PRD states these rules without inventing error ids; `ERR_VISIT_WINDOW_PAST` is attached only to the not-in-the-past rule, exactly as the error catalog nominates.

## Notable wording decisions

- Pseudocode translated throughout: `ceil` → "rounded up to a whole number", `floor` → "partial minutes discarded", `min(100,…)` → "capped at 100", `>=` → "at least", strict `>` → "strictly exceeds" (SLA equality pinned as compliant; visit photo-count equality pinned as sufficient).
- Discount tiers stated in cents with dollar gloss ("500,000 cents ($5,000.00)") to keep reconstruction exact.
- §2.9 names the two OCC endpoint paths explicitly (allowed in §2; §3 stays path-free via state-transition/role-verb framing).
- `GET` endpoints' roles rendered as "All authenticated roles" in §4 (Anonymous is excluded per §2.1).
- One fuzzy-word false positive ("opinionated about") reworded to "opinionated on" for a clean scan.

## Step 5: Generate Unit Tests — 2026-08-11T07:56:00.000Z

Test generation complete. Summary:

## test_helpers/ (9 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing/test_helpers/types.py` — 14 entity TypedDicts (all carry id/created_at/updated_at/version), 20 status/domain enums, UserRole
- `api_client.py` — `ApiClient(GenericApiClient)` with 41 endpoint methods covering every PRD endpoint incl. `/_clock/set_current_utc`
- `api_errors.py` — `ApiErrorId` (37 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_invoice_invariants` (pre-discount/total reconciliation)
- `factories.py` — payload factories; SEA/PDX/TAC market presets
- `constants.py` — hazard weights/bands, priority multipliers, discount tiers, variance cap, offer expiry, clock default
- `test_users.py` — shared headers for opaque roles; `make_customer_headers`/`make_subcontractor_headers` builders for entity-backed ownership
- `fixtures.py` — ~40 step helpers (auto-OCC scope/artifact adds via fresh parent-version reads) plus composite tiers: `setup_network`, `setup_dispatched_job`, `setup_on_site_job`, `setup_secured_job`, `extend_*` variants for multi-job tests sharing one market, `setup_complete_package`, `setup_billing_ready`, `setup_removed_job`, `setup_closed_job`
- `__init__.py` — barrel export

## test_suite/ (9 files)
`conftest.py` + `test_01_network_intake.py` (12), `test_02_dispatch_offers_sla.py` (10), `test_03_safety_assessments.py` (6), `test_04_scope_and_securing.py` (15), `test_05_services_patrols_breach.py` (12), `test_06_permits_billing_invoices.py` (23), `test_07_subcontractor_lifecycle.py` (6), `test_08_job_closure.py` (5).

## Counts
- **Total tests: 89** — Queue A (Difficulty): **38** (19 instances × exactly 2 tests); Queue B (Corner): **51** (all 51 non-stub instances × 1 test).
- All 19 queue-A instances and all 51 queue-B non-stub instances passed the PRD-first two-condition filter; **no instances skipped**.
- 8 corner `excluded_because:` stubs correctly not translated; all 8 `difficulty_instance` pointers verified to resolve to real queue-A instances.

## Notable adjudications
- `variance_cap_exceeded_then_override`: the recipe's install payload (2 openings at 48×36 → 1 sheet = 4000) cannot produce its own asserted 8000 work subtotal; I adjusted the setup to 3 openings (36 sqft → 2 sheets = 8000), preserving every asserted literal (cap 4800, total 33000).
- `notification_pending_submit_rejected`: recipe omitted the mandatory `expected_package_version` on one artifact add; restored it (OCC fields are non-optional per PRD §2.9).
- Relaxed two created_at-tie orderings (pagination identity, re-offer list position) to set/status-based assertions — PRD pins `created_at` ASC but not the tiebreak, and both rows share the default-clock timestamp.
- Multi-job tests (hazard bands, generator pool) use shared-network `extend_*` fixtures so the unique market code isn't duplicated mid-test and the generator pool stays market-scoped.

## Verification results
- `python3 -m py_compile`: all 18 files pass.
- Import check: all 8 test modules import against `test_helpers` with no missing names.
- `pytest --collect-only`: **89 tests collected**, no errors.
- Citation audit (script run, then removed): every test has exactly one `Design:` tag as the last docstring line, every tag resolves to a real instance, and every ≥8-word quoted PRD span survives a whitespace-normalized verbatim substring check against `PRD.md` — clean after fixing 7 quotes that had crossed PRD bold markers or ellipses.
- No `pytest.mark.skip`/`skipif`/`xfail`, no scaffold references in comments/docstrings.

## Step 6: Generate Implementation — 2026-08-11T08:10:00.000Z

All processes cleaned up. Implementation is complete.

## Summary

**Implementation complete** at `/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing/workspace/implementation/`.

### File list (sizes in bytes)

```
  263 start.sh
   11 requirements.txt
 1995 app.py
 1720 db.py
 1757 errors.py
 1347 response.py
 2051 middleware.py
 7360 services/common.py
 4189 services/dispatch.py
    0 services/__init__.py
 9829 routes/network.py      (markets, subcontractors, coverages, customers, properties)
10848 routes/jobs.py          (job lifecycle: intake/dispatch/check-in/complete/verify/removal/close)
 4044 routes/assignments.py   (get/list/respond/withdraw)
 5179 routes/safety.py        (safety assessments + mitigate)
 5213 routes/scope.py         (scope items add/list/install/void with OCC)
11000 routes/services.py      (temporary services + patrol visits + breach cascade)
 4950 routes/permits.py       (permit cases + file + record-decision + lazy expiry)
 3244 routes/documents.py     (document packages + artifacts with OCC)
11222 routes/invoices.py      (invoices + submit gates + dispute + payment)
 1231 routes/clock.py         (POST /_clock/set_current_utc with notification sweep)
    0 routes/__init__.py
```

### Verification results

- **Route count**: 55 endpoints registered, exactly matching SCAFFOLD.yaml endpoint table
- **Entity/store count**: 14 in-memory dicts (markets, subcontractors, coverages, customers, properties, jobs, assignments, safety_assessments, scope_items, temporary_services, patrol_visits, permit_cases, document_packages, invoices) — all in `db.py`, all start empty, no seeding
- **py_compile**: all 19 .py files compile cleanly
- **Boot check**: `start.sh` is executable, boots Flask on 0.0.0.0:$PORT (tested on 18765/18766), responds 401 with proper envelope (`meta`/`response_type`/`data.error_id`) to unauthenticated GET, and 200 to the clock endpoint with admin auth
- **End-to-end smoke test**: market → subcontractor → coverage → customer → property → job → dispatch → accept → check-in → scope-item add (with OCC `expected_job_version`) all succeed with correct status codes and envelope; BOARD material calculation verified (2×36"×48" → 24 sqft → 1 sheet)

### Key design choices

- **In-memory storage**: Python dicts in `db.py`, no disk persistence, empty at boot
- **Logical clock**: pinned at `2026-05-01T00:00:00Z` startup, set via `POST /_clock/set_current_utc`, sweeps PENDING NOTIFICATION cases to EXPIRED and latches `compliance_breach`; also lazily expires on read/submit
- **Money**: `Decimal` with `ROUND_HALF_UP` throughout; per-line rounding before summation for work lines; per-visit rounding for patrol fees
- **Validation precedence**: auth (401) → role/ownership (403) → well-formedness (400) → existence (404) → state (409) → safety/regulatory (409) → temporal (409) → structural (409/422) → fiscal (409) → OCC (412)
- **Cascades**: suspension cascade (cancels assignments, regresses jobs), patrol-miss breach cascade (service → job BREACH_HOLD → sibling services + replacement visit +24h), offer re-offer cascade with decline/expire/cancel exclusion
- **OCC**: `expected_job_version` on scope-item add, `expected_package_version` on artifact add — both checked last after all other gates
- **start.sh**: guards `pip install` with `import flask` check to avoid contended installs on per-test reboots; uses `exec` to hand off to python3 in foreground

## Step 7: Run Tests and Iterate — 2026-08-11T08:24:00.000Z

**Summary**

- **Iterations run:** 2 sweeps (initial diagnostic sweep: 82/89 × 8 rounds, identical deterministic failures; post-fix sweep: 89/89 × 8 rounds — clean).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing/test_helpers/assertions.py` — added `parse_iso8601` / `assert_same_instant`: PRD pins the *instant* clock-stamped fields must hold (§2.5 clock start, §3.2 +30 min offer expiry, §3.6 +24 h replacement window, §3.7 secured_at + deadline) but does not pin their string rendering (only `created_at` is pinned to three fractional digits in §2.4), so exact-string equality on unpinned fields is not uniquely derivable (STEP 1c split: kept the covered instant assertion, dropped the uncovered rendering assertion).

- **Fixes applied to `test_suite/`:**
  - `test_01_network_intake.py::test_market_creation_echo_and_system_fields` — `created_at` expectation changed to `"2026-05-01T00:00:00.000Z"`; the old `"…00Z"` expectation contradicted PRD §2.4 verbatim ("three fractional digits").
  - `test_01_network_intake.py::test_job_initial_state_intake`, `test_02_dispatch_offers_sla.py::test_sla_exact_minute_compliant_at_boundary` and `::test_clock_default_timestamp_on_dispatch`, `test_05_services_patrols_breach.py::test_patrol_missed_spawns_replacement_visit`, `test_06_permits_billing_invoices.py::test_notification_late_filing_penalty_billed` — `reported_at`/`offered_at`/`offer_expires_at`/`window_start`/`window_end`/`deadline_at` assertions switched to `assert_same_instant` (instant is PRD-pinned; string form is not).

- **Fixes applied to `implementation/`:**
  - `services/common.py` — added `find_current_assignment(job_id)`: latest ACCEPTED/ARRIVED/COMPLETED assignment by `offer_seq`, i.e. PRD §2.1's "currently accepted assignment" whose status may have advanced since acceptance.
  - `routes/jobs.py::complete_securing` — assignee gate now uses `find_current_assignment`; previously the finder ignored COMPLETED assignments, so the PRD §3.6 re-secure cycle ("the crew re-completes securing") 403'd with `ERR_NOT_ASSIGNEE` on the second ON_SITE pass. Counter-settling remains guarded on ARRIVED, so no double-count.
  - `routes/scope.py::install_scope_item` — same finder swap (same §2.1/§3.5 assignee sentence; previously the assignee could never install on the post-breach ON_SITE pass).
  - `routes/services.py::check_in_patrol_visit` — replaced the ad-hoc ACCEPTED/ARRIVED + inline COMPLETED fallback with `find_current_assignment` (behavior-identical simplification).
  - `routes/safety.py::create_safety_assessment` — segregation-of-duties check now uses `find_current_assignment`; previously in BREACH_HOLD (assignment COMPLETED) the lookup returned None and the PRD §3.4 `ERR_SEGREGATION_OF_DUTIES` check was silently skipped.

Orchestrator verification: all 8 `results.*.json` files present on disk; every round reports passed=89/89, failed=0.

## Step 8: Finalize PRD — 2026-08-11T08:36:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing/workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 322 lines; PRD_FINALIZED.md: 324 lines; delta +2 lines (+0.62%), 4 inline edits, no new sections.

## Changes (one bullet per edit)
- **§2.4** — insert — added a sentence pinning uniform three-fractional-digit UTC rendering for every emitted timestamp (`updated_at`, `api_request_timestamp`, `current_utc`, and all clock-stamped business fields), with client-supplied timestamps echoed back normalized — `implementation/db.py:32-38` (`format_ts`), `implementation/db.py:28-29` (`iso_now`), `implementation/response.py:18-20`, `implementation/routes/clock.py:34`, `implementation/routes/services.py:67-68,163-164`.
- **§2.1** — revise — defined "a job's *currently accepted assignment*" as the job's latest-by-`offer_seq` assignment in `ACCEPTED`, `ARRIVED`, or `COMPLETED` status, retaining the assignee role after status advances (covers the §3.6 re-secure pass and §3.9 removal) — `implementation/services/common.py:160-170` (`find_current_assignment`).
- **§3.4** — revise — bound the segregation-of-duties reference to "the `subcontractor_id` of the job's currently accepted assignment (§2.1), which in `BREACH_HOLD` has already advanced to `COMPLETED`" — `implementation/routes/safety.py:45-50`.
- **§3.5** — revise — pinned that SLA counter settlement rides on the assignment's own `ARRIVED` → `COMPLETED` transition, so the re-secure pass (assignment already `COMPLETED`) moves the job and resumes services without re-settling counters — `implementation/routes/jobs.py:180-190`.

Step 7 diff items needing **no** PRD edit: the `test_01` `created_at` ".000Z" fix (pure fixture bug; PRD §2.4 already pinned verbatim), and the `services.py` patrol check-in finder swap (explicitly behavior-identical simplification).

## Per-edit pre-edit search log
1. **Timestamp rendering (§2.4).** (a) Subject: string rendering of every emitted timestamp. (b) Enumerated: grepped all `iso_now()`/`format_ts(`/`strftime`/`isoformat`/`datetime.now` call sites — every entity field (`reported_at`, `dispatched_at`, `offered_at`, `offer_expires_at`, `responded_at`, `arrived_at`, `secured_at` in jobs.py/dispatch.py/assignments.py; `deadline_at`, `filed_at` in permits.py; `submitted_at`, `paid_at` in invoices.py; `starts_at`, `ends_at`, `deactivated_at`, `window_start`, `window_end`, `checked_in_at` in services.py), plus `current_utc` (clock.py:34), `api_request_timestamp` (response.py:18-20, also 3-frac-digit), and client-supplied windows normalized via `parse_ts`→`format_ts`. All emit exactly three fractional digits. (c) Added "client-supplied timestamps are echoed back in that same normalized form" to cover services.py:67-68/163-164; explicitly included `api_request_timestamp` (already pinned in §2.2) and `current_utc` so the sentence is exhaustive over enumerated paths.
2. **"Currently accepted assignment" (§2.1).** (a) Subject: which assignment satisfies a job-level assignee gate. (b) Enumerated every assignee-lookup path: `routes/jobs.py:162` (complete_securing → find_current_assignment), `routes/jobs.py:229-233` (record_removal → inline latest ACCEPTED/ARRIVED/COMPLETED by offer_seq — identical semantics), `routes/jobs.py:128-134` (check_in_job → inline ACCEPTED-only, matching §3.3's backticked "currently `ACCEPTED` assignment"), `routes/scope.py:83`, `routes/services.py:198`, `routes/safety.py:48`, per-assignment checks in `routes/assignments.py:52` (respond) and withdraw, and `services/dispatch.py:96` (`find_accepted_or_arrived_assignment`, internal cascade suppression — not an assignee check). Also verified no path can re-dispatch a job holding a COMPLETED assignment (withdraw limited to OFFERED/ACCEPTED per assignments.py:86; suspension cancels only OFFERED/ACCEPTED/ARRIVED per network.py:99), so the offer_seq tiebreak coincides with first-found in check_in's reachable states. (c) Scoped the sentence to "assignee checks" only (not cascade suppression) and used "latest by `offer_seq`" rather than claiming a global at-most-one invariant, keeping §3.3's status-specific rule untouched.
3. **Segregation of duties (§3.4).** (a) Subject: the reference assignee for `ERR_SEGREGATION_OF_DUTIES`. (b) Enumerated: sole site is `routes/safety.py:48-50`; cross-checked against the §2.1 definition from Edit 2. (c) Wording defers to §2.1 ("currently accepted assignment") instead of redefining, and says "in `BREACH_HOLD` has already advanced to `COMPLETED`" — consistent with create_assessment's reachable states (`ON_SITE`/`BREACH_HOLD` only, safety.py:37).
4. **Counter settlement (§3.5).** (a) Subject: whether re-completing securing re-settles `completed_job_count`/`breached_job_count`. (b) Enumerated: grepped all mutations of both counters — only `routes/jobs.py:186-188`, guarded by `assignee["status"] == "ARRIVED"` at jobs.py:180; job transition/`secured_at` re-stamp (177-178) and PAUSED→ACTIVE resume (192-195) are unconditional. (c) Wording attributes non-settlement specifically to the assignment's already-`COMPLETED` status and explicitly preserves the job move + service resume, matching all three code blocks; no other counter path exists to be mis-described.

## Step 9: Complete PRD — 2026-08-11T09:04:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size:** PRD_FINALIZED.md 324 lines / 57,759 chars → PRD_COMPLETED.md 328 lines / 63,508 chars (**+4 lines, +5,749 chars**). No new sections; all changes are in-paragraph inserts/revisions.

**Counts:** 15 ambiguity-pins, 3 mismatch-revisions (18 edited passages total).

**Changes (one per bullet):**

- §2.2 — insert — mismatch — pinned `api_request_timestamp` as stamped from server **wall-clock** (transport metadata), carving it out of §2.5's "never wall-clock" claim — implementation/response.py:17-20
- §2.2 — insert — ambiguity — unknown paths / unsupported methods → `ERR_NOT_FOUND` (404); unexpected internal failure → `ERR_INVALID_REQUEST` with HTTP 500 — implementation/app.py:27-42
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are **clamped** (1..100, 0 floor) not rejected; non-integer → `ERR_INVALID_REQUEST`; pinned `total_count` = filtered size pre-pagination, `has_more` ⇔ `offset + returned < total_count` — implementation/middleware.py:47-66, response.py:32-44
- §2.5 — revise — mismatch — clock-set applies `to_iso8601` unconditionally (no monotonicity check, backward allowed); sweep/lazy-expire trip strictly past deadline; lazy expiry fires on case **read or list** — implementation/routes/clock.py:12-34, routes/permits.py:14-30,80-81
- §2.7 — revise — mismatch — rewrote the validation-precedence stage list to impl's true order (12 stages): auth → endpoint role → **path existence before body** → well-formedness → **job CLOSED guard before ownership** on `/jobs/{id}...` endpoints → ownership/assignee → state eligibility (body FK refs verified where consulted) → safety gates → temporal → structural → fiscal → OCC last; noted window-timestamp parsing fires after the state gate on service/visit creation — e.g. implementation/routes/assignments.py:45-65, routes/jobs.py:121-136,222-241, routes/services.py:22-45,126-143
- §2.9 — insert — ambiguity — non-integer OCC guard field → `ERR_INVALID_REQUEST` before comparison — implementation/routes/scope.py:36-40, routes/documents.py:68-72
- §3.1 — insert — ambiguity — all named market fields required at creation; duplicate `code` → `ERR_INVALID_REQUEST` — implementation/routes/network.py:23-35
- §3.1 — insert — ambiguity — subcontractor PATCH accepts only `ACTIVE`/`SUSPENDED` (`ERR_INVALID_ENUM` otherwise); no-change/status-omitted patch is a no-op — implementation/routes/network.py:88-94
- §3.2 — revise — ambiguity — pinned dispatch requires an **ACTIVE** coverage row; missing or suspended row → `ERR_MARKET_MISMATCH` — implementation/routes/jobs.py:98-105
- §3.2 — insert — ambiguity — re-offer cascade is a no-op while an `OFFERED`/`ACCEPTED`/`ARRIVED` assignment remains; on an `ON_SITE` job (arrived crew suspension-cancelled) a re-offer returns it to `DISPATCHED` with `dispatched_at` re-stamped, empty pool regresses `ON_SITE` → `INTAKE` — implementation/services/dispatch.py:86-113
- §3.4 — insert — ambiguity — assessor's own record must exist (`ERR_NOT_FOUND`) and be `ACTIVE` (`ERR_SUBCONTRACTOR_SUSPENDED`), checked after the state gate, before segregation; `hazards` required, must be an array (`ERR_INVALID_REQUEST`), bad member → `ERR_INVALID_ENUM` — implementation/routes/safety.py:28-44
- §3.5 — revise — ambiguity — scope items may be added in `INTAKE`/`DISPATCHED`/`ON_SITE`/**`BREACH_HOLD`** (not merely "until SECURED"); missing, non-numeric, or non-positive measurements → `ERR_INVALID_MEASUREMENT` — implementation/routes/scope.py:26-34, services/common.py:224-256
- §3.5 — insert — ambiguity — install-time omitted measurement fields fall back to the item's planning-time values; supplied measurements are persisted onto the item — implementation/routes/scope.py:92-101
- §3.6 — revise — mismatch — visit window: end not strictly after start → `ERR_INVALID_REQUEST` (PRD had said both violations → `ERR_VISIT_WINDOW_PAST`); end not strictly after clock → `ERR_VISIT_WINDOW_PAST`; `ERR_SERVICE_NOT_PATROL` fires before window validation — implementation/routes/services.py:132-143
- §3.6 — insert — ambiguity — services creatable only while job is exactly `SECURED`; non-positive span → `ERR_INVALID_REQUEST`; `generator_units` non-integer/<1 → `ERR_INVALID_REQUEST`; overlap check considers only `SCHEDULED` visits — implementation/routes/services.py:29-45,144-154
- §3.7 — insert — ambiguity — PERMIT cases openable in any non-`CLOSED` job state; NOTIFICATION requires exactly `SECURED` — implementation/routes/permits.py:40-44
- §3.8 — insert — ambiguity — package creation allowed in `SECURED`, `BREACH_HOLD`, `READY_FOR_REMOVAL`, `REMOVED`; docs gate: job with **no** package also fails `ERR_DOCS_INCOMPLETE`; work-line `label` = item `kind`, lines in scope-item creation order; multiple unbilled late filings billed one case per invoice, earliest first — implementation/routes/documents.py:21-25, routes/invoices.py:43-50,75-81,190-192
- §4 — revise — ambiguity — extended the 200 OK list to pin offer responses, mitigation recordings, installs/voids, patrol outcomes, **artifact additions (200, mutates package)**, and subcontractor patches; updated scope-items and document-packages table cells to match §3.5/§3.8 — implementation/routes/documents.py:81, routes/network.py:128

Everything else in the PRD (state machines, formulas, hazard weights, rounding rules, SLA evaluation, breach cascade, invoice computation order, error catalogue, endpoint table, OCC surface) was verified against the implementation and already pinned uniquely — no change needed.
