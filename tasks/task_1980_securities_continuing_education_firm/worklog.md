# Worklog — task_1980_securities_continuing_education_firm

## Step 1: Create Task Directory — 2026-08-15T00:00:00.000Z

Pre-existing: `tasks/task_1980_securities_continuing_education_firm/` and `workspace/` already created by pipeline launcher; index 1980 assigned externally.

## Step 2: Generate Scaffold — 2026-08-15T00:00:00.000Z

Scaffold generation complete and lint-clean. Summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/`):
- `SCAFFOLD.yaml` (1187 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (628 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1144 lines) — single top-level key `scaffold_corner_design`

**SCAFFOLD.yaml contents** (Expert band):
- **12 entities**: Representative, TrainingContent, CourseSession, Enrollment, RegulatoryAssignment, FirmElementPlan, AnnualAttestation, ProductOffering, ProductCertification, StateCELicense, TrainingBlackoutWindow, AuditEvent (append-only, `common_fields: false`)
- **9 state machines** — non-linear ones: content approval rework cycle (DRAFT→PENDING→REJECTED→DRAFT), enrollment retake cycle (FAILED→ENROLLED→…→COMPLETED), assignment lapse/cure paths (ASSIGNED→OVERDUE→LAPSED→COMPLETED), plan reopen loop (CLOSED→PLAN_PUBLISHED on void)
- **9 calculations**, incl. dual variants (plan certified-vs-projected hours; state-CE strict-vs-carryover hours), capped-surcharge required-hours formula, per-course-then-sum half-hour rounding, seat ledger, deadline/selector rules
- **54 endpoints** (flat topology, filtered-list reverse reachability for all 14 FKs), **39 error codes** (all exercised by ≥1 design instance), **4 roles** (TrainingAdmin/ComplianceOfficer opaque, RegisteredRep entity-backed, Auditor read-only), **2 OCC concurrency rules** (plan-create supersedes on Representative.version; content edit on TrainingContent.version), logical clock with pinned default `2026-08-01T00:00:00Z` plus an explicit enforcement-sweep ops-run endpoint

**Design indices**:
- **18 difficulty instances** (9 rules × 2), all with structured `setup_api_calls` chains and precomputed literal asserts (e.g., required_hours == 18 with the product cap binding; reported 5.0 vs raw 4.5 proving rounding order; due_at == 2026-11-29T00:00:00Z inclusive-boundary completion)
- **64 corner instances**: 57 active + 7 `excluded_because` stubs pointing at difficulty instances

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (527 calls scanned)

**Design decisions worth noting**:
- Chose *compliance/audit × temporal windowing* archetypes with a *segregation-of-duties* role model (author ≠ approver by X-User-ID; reps attest/complete only their own records; only ComplianceOfficer voids) — matching the scenario's regulatory character
- Rule-8 contrast is geometric: room booking uses half-open semantics (back-to-back allowed) while blackout windows use closed semantics (touching endpoints conflict)
- Rule-4 cascades: sweep-driven lapse chain (assignment→registration→certification suspension) and audit-void chain (void→plan reopen→attestation voided), each hop caused by the previous hop's mutation
- Deadline enforcement is fully deterministic: the clock-set endpoint never mutates entities directly; all time-driven transitions fire only through `POST /enforcement/sweep`, and validation-time enrollment expiry is deliberately decoupled from sweep-time state expiry (covered by a dedicated corner instance)

## Step 3: Copy Shared Files — 2026-08-15T00:00:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1980_securities_continuing_education_firm/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T00:00:00.000Z

All verifications pass. The PRD is complete.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/workspace/PRD.md` — 367 lines, 59,560 bytes.

**Section structure** (domain-derived, not copied from the example):
- §1 Introduction — 3 paragraphs (regulatory/firm-element/product/state-CE business context → system scope → audit evidence)
- §2 Global Specifications — 10 subsections: 2.1 Roles & identity semantics, 2.2 Response Structure (verified **byte-identical** to the fixed verbatim block), 2.3 Pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending), 2.4 Logical Clock & Deadline Enforcement (startup default `2026-08-01T00:00:00Z`, pinned sweep order), 2.5 Common Resource Properties (incl. AuditEvent's `common_fields: false` exception), 2.6 Request Validation Order (explicit 12-stage ordered chain, first-match-wins), 2.7 OCC, 2.8 Credit-Hour Precision & Rounding, 2.9 Audit Evidence, 2.10 Cascades & Atomic Side Effects
- §3 Business Logic — 9 subsections by domain workflow (reps → content → sessions → enrollments → assignments → plans/attestations → products/certs → state CE licenses → sweep)
- §4 Endpoint table — 54 rows, 4 columns only (matches scaffold's 54 endpoints)
- §5 Error catalogue — 40 rows, 2 columns (note: the calibration header claims 39, but the actual `errors[]` table contains 40 entries; all 40 rendered)

**Hard contract reports**:

```
Field coverage check:
- entities[].fields: 75 required, 75 present, 0 missing
- endpoints[].request_body/inputs: 41 required, 41 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
- endpoints[].path_params: 11 required, 11 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ field + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 39 checked across 9 machines, 39 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (constants 120d/30d/90d/3 attempts/12/16/2/3/6h/0.5 embedded; pinned orders; no pseudocode), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 checked, 54 expressed, 0 missing
- entities[].fields[] structured content: 75 checked, 75 reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (terminate ×2, cancel ×2, expire ×2, assignment-complete ×3, assignment-lapse ×2, renew ×2, PUT ×2, cert-suspension reasons ×5), 8 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 614
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Decisions worth noting**:
1. Boundary inclusivity is spelled out everywhere it matters: exactly-at `expires_at` still valid, exactly-at `due_at` on time, strictly-past `lapse_after` lapses, reached-or-passed `end_at` delivers sessions, half-open license hour windows vs. closed blackout intervals (touching boundaries conflict), back-to-back room bookings allowed.
2. All cascades rendered with full secondary effects: lapse → registration flip → cert suspension chain; void → plan reopen → attestation void; retire → enrollment/session/cert triple cascade; the five `suspended_reason` causes each named with their triggers.
3. `reported_hours` per-course-before-sum pinned order is expressed with the conforming example (two 1.25-hour courses → 3.0, not 2.5) so a PRD-only reader can reconstruct `round_half_up(x*2)/2` per course then sum.
4. The 15 validation priorities are rendered as an explicit ordered 12-stage chain in §2.6 (auth → role → existence → shape → OCC → state → registration → SoD/ownership/needs-analysis → uniqueness → referential → temporal → capacity/fiscal/retake/reinstatement), with OCC explicitly "after existence and shape, before business checks."
5. OCC prose avoids all race-framing ("simultaneously", "first-writer-wins"); the two version fields are justified by the mutations they guard (plan creation bumps `Representative.version`; content edits bump `TrainingContent.version`).
6. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, per the constraint.

## Step 5: Generate Unit Tests — 2026-08-15T00:00:00.000Z

Clean. Final summary of the work:

## Summary

**Generated for** `task_1980_securities_continuing_education_firm`.

### Test count by queue
- **Queue A (Difficulty)** — 18/18 instances covered, ≥2 tests each: **42 tests**
- **Queue B (Corner)** — 57/57 non-stub instances covered, ≥1 test each: **64 tests**
- **Total: 106 test functions**, all tagged with exactly one `Design:` line resolving to a real instance. The 7 `excluded_because:` stubs were not translated (verified their `difficulty_instance` pointers resolve to queue-A instances that own those assertions).

### Skipped instances
None. Every non-stub instance passed the PRD-first two-condition filter — the PRD contains verbatim, uniquely-deriving prose for every asserted rule (all 106 docstring citations machine-verified against PRD.md with ≥8-word literal substrings; 0 failures).

### Helper infrastructure (`test_helpers/`)
- `types.py` — 12 entity TypedDicts (AuditEvent correctly omits `updated_at`/`version` per PRD §2.5) + status/role enums
- `api_client.py` — 45 methods covering all 54 scaffold endpoints
- `api_errors.py` — 39 error IDs + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + seat invariant
- `factories.py` — payload factories (input fields only, unique crd/code sequencing)
- `constants.py` — thresholds (120d/30d/90d, MAX_ATTEMPTS 3, carryover cap 6, surcharge cap 3, floor 6) + clock default
- `test_users.py` — `TEST_USERS` for opaque roles + `make_rep_headers(user_id)` builder (mandatory for the entity-backed RegisteredRep role on ownership-gated calls) + `make_admin_headers`/`make_officer_headers` for SoD-pinned identities
- `fixtures.py` — composite setups: `create_approved_content`, `create_published_plan`, `setup_closed_plan_with_attestation`, `setup_certified_rep`, `setup_lapsed_rep_with_certified_product`, `complete_state_insurance_course`, `create_instructor_led_setup`, `void_enrollment`, clock control, etc.
- `__init__.py` — barrel export (framework + PRD-specific)

### Test organization (`test_suite/`)
`conftest.py` + 11 numbered files by concern: content workflow (rework/retake cycles, OCC), plan hours (dual variants, required-hours formula, invariants), state CE (strict-vs-carryover, per-course rounding), enrollment lifecycle (guards, retake budget, score boundary, expiry), sessions/rooms/blackouts, enforcement sweep + cascades (lapse depth-3, void depth-3, due/overdue boundaries), plans/attestations, products/certifications, representatives/validation ordering, RBAC/SoD/audit/pagination, content guards/uniqueness.

### Design decisions worth noting
- **Priority-pair instances**: the two difficulty `priority_pair_validation_conflict` tests assert the winning error where PRD §2.6's numbered chain uniquely determines it (existence #3 before registration #7; state #6 before SoD #8; uniqueness #9 before capacity #12). Companion tests isolate each rule on its own.
- **Boundary instances**: `due_at`/`lapse_after`/expiry arithmetic verified against the PRD's logical-clock default (2026-08-01T00:00:00Z + 120d = 2026-11-29T00:00:00Z, +90d = 2026-10-30T00:00:00Z) — tests use the design indices' exact timestamps.
- **`required_hours == 18`** uses PRD §3.6's pinned evaluation order (base → capped surcharge → excess → floor); the floor-binding corner asserts 6 for RR with excess 9.
- Suite collects cleanly under pytest (106 tests, no import errors); no skip/xfail marks anywhere.

## Step 6: Generate Implementation — 2026-08-15T00:00:00.000Z

All four smoke phases pass on fresh server boots. The implementation is complete.

## Summary

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/workspace/implementation/`)

```
start.sh            # exec-foreground launcher; pip install guarded on `import flask`; PORT env (default 10000), 0.0.0.0
requirements.txt    # flask>=2.2
app.py              # Flask app factory, blueprint registration, envelope-aware error handlers (ApiError/404/405/400/500)
db.py               # in-memory Store (12 dicts), logical clock (default exactly 2026-08-01T00:00:00Z), base_record/touch/audit helpers
errors.py           # ApiError + all 39 error-id constants
response.py         # success/error envelope (meta.api_request_id/api_request_timestamp, response_type, data), limit/offset pagination (default 10, 1..100, offset 0)
middleware.py       # X-User-ID/X-User-Role validation, per-endpoint role enforcement, JSON body helpers
util.py             # ISO8601 parse/format (3 fractional digits, seconds-truncated), Decimal helpers, q2/round-to-0.5, field validators, view serializer
services.py         # all business logic: seat accounting, plan/license recomputes, required-hours calc, lapse/restore/terminate/retire/void/cancel cascades, launch fan-out, reinstatement gates, 4-phase enforcement sweep
routes/
  representatives.py  contents.py  sessions.py  enrollments.py  assignments.py  plans.py
  attestations.py     products.py  licenses.py  blackouts.py    ops.py (sweep + _clock + audit-events)
```

### Endpoint coverage: 54/54
Verified programmatically that exactly 54 routes register — matching the scaffold's `endpoint_count: 54`.

### Verification performed
179 smoke assertions across four live-server test phases, all passing on fresh `bash start.sh` boots (matching the per-test-server restart model): auth/RBAC, envelope shape, every error catalog entry exercised with correct HTTP codes, validation precedence (existence>state, state>SoD, duplicate>capacity), OCC on both versioned endpoints, all 9 state machines including cascades, calculations with the pinned examples from the difficulty-design doc (certified 3.0 vs projected 5.0; strict 2.0/effective 7.0/carried 5.0; reported per-course 1.25+1.25→3.0; principal 16+6−4 capped → verified 19 with 4 products; floor at 6), seat invariant across fail/reattempt/cancel, sweep phase order + boundary inclusivity (due_at inclusive, expires_at exclusive), and audit-log actor rules. start.sh contract verified: HTTP-ready in ~1s, 0.0.0.0, exec foreground, zero entities at boot.

### Implementation decisions worth noting
- **Logical clock everywhere for entity data**: all timestamps stored as datetimes truncated to whole seconds (PRD mandates 1-second-precision comparisons) and rendered as `.000Z`; the envelope's `api_request_timestamp` uses wall-clock UTC (PRD describes it as server request metadata; sibling passing implementations do the same).
- **Decimal everywhere for hours**; serialized as int when integral, else exact float.
- **FAILED releases its session seat; reattempt re-consumes it** — the seat-holding set is exactly {ENROLLED, IN_PROGRESS, COMPLETED} per the scaffold invariant.
- **Registration guard enforced strictly on enrollment create/start/complete/reattempt** (per PRD §3.1/§3.4, scaffold validations 4.1, and the corner-design doc, which never completes training while INACTIVE_CE). The cure/restoration cascade (LAPSED→COMPLETED, INACTIVE_CE→ACTIVE with cert reinstatement) is fully implemented and reachable whenever a completion lands while an assignment is open; under the strict guard the sweep-lapsed cure is blocked at complete — this matches the task's own corner-design fixtures (`c_enroll_while_registration_inactive_returns_409`, `c_reinstate_blocked_while_rep_inactive_returns_409`).
- **Audit events**: primary event written last in each cascade per PRD prose ordering; sweep-generated events (including ENFORCEMENT_SWEEP_RUN) use actor `system`/`system`; termination-voided PENDING attestations deliberately get no ATTESTATION_VOIDED event.
- **No seeding**: the store boots empty; every entity is creatable via the declared API surface.
- Void-driven assignment reversion uses the current clock bands (ASSIGNED/OVERDUE/LAPSED) and re-runs the registration cascade only on the LAPSED band — verified in both bands.

## Step 7: Run Tests and Iterate — 2026-08-15T00:00:00.000Z

All 8 rounds pass 106/106. Clean stability sweep — exiting with the summary.

---

## Summary

**Iterations run:** 2 (initial sweep surfaced 8 deterministic failures, identical across all 8 rounds; post-fix sweep passed 106/106 in all 8 rounds)

**Tests deleted:** None. Every failing test traced to verbatim PRD prose, so no deletions were warranted.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/test_helpers/fixtures.py` — fixture `complete_state_insurance_course`: first parameter was named `rep_id` while the body dereferenced `rep["id"]`, raising `NameError: name 'rep' is not defined` in all 6 state-CE tests that call it (callers pass the rep dict, per the fixture's docstring). Renamed the parameter to `rep`. One upstream fixture bug had masqueraded as 6 independent implementation-looking failures across `TestStateCeStrictVsCarryover`, `TestReportedHoursPerCourseRounding`, and `TestLicenseHoursReconcileOnVoid`.

**Fixes applied to `test_suite/` (partial-coverage corrections per STEP 1c — kept the PRD-pinned instant assertion, dropped the non-derivable serialization-format equality):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/test_suite/test_06_enforcement_and_cascades.py` — `TestDueBoundary::test_completion_at_due_at_completes_assignment`: asserted `completed_at == "2026-11-29T00:00:00Z"` (exact string). PRD §3.4 pins the instant ("`completed_at` is stamped from the logical clock") but never pins zero-fractional-digit rendering for derived timestamps (§2.5 mandates three fractional digits only for `created_at`; §2.2's example shows `.123Z`). Now parses the response and compares instants against `datetime(2026, 11, 29, tzinfo=utc)`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/test_suite/test_10_rbac_and_audit.py` — `TestInitialStates::test_assignment_created_assigned_with_computed_deadlines`: same collapse on `due_at`/`lapse_after` string equality. PRD §3.5 pins the arithmetic ("`due_at` is exactly 120 days after creation, and `lapse_after` is a further 30 days beyond that"); the test still asserts those exact instants, now via parsed-datetime comparison instead of format-prescriptive string equality.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful on every failing path — license hour counters (strict/effective/per-course-rounded reported, carryover cap 6, void reconciliation), assignment deadline arithmetic (created + 120d / + 30d), and uniform three-fractional-digit timestamp serialization all matched PRD verbatim. No implementation check was added, removed, or weakened.

**Feedback notes for generators:**
- unit-test-generator: the 6 state-CE tests were correct; the scaffold-driven fixture they share had a param-name/body mismatch (`rep_id` vs `rep`) — a fixture-implementation miss, not a PRD-coverage miss.
- unit-test-generator (unique-derivability): two tests asserted exact timestamp strings (`...T00:00:00Z`) for derived fields where PRD pins only the instant and the three-fractional-digit rule only for `created_at` — classic format-overreach; timestamp assertions should compare parsed instants unless PRD verbatim-pins the rendering.

## Step 8: Finalize PRD — 2026-08-15T00:00:00.000Z

Done. The diff is exactly one revised line (the `%`-format crash in my stats snippet is cosmetic; the numbers printed before it).

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 367 lines (59,369 chars); PRD_FINALIZED.md = 367 lines (59,991 chars). Line delta: +0 lines (0.00%); character delta: +622 chars (+1.05%). Exactly one bullet revised, no sections added.

**Changes (one bullet per change):**
- **§2.2 (Standard Success Response Format)** — **revise** — extended the `api_request_timestamp` bullet to pin that *every* timestamp the server emits is rendered ISO 8601 UTC with exactly three fractional digits (resource `created_at`/`updated_at`, workflow stamps such as `due_at`, `lapse_after`, `expires_at`, `completed_at`, `start_at`, `end_at`, `period_start`, `period_end`, `launched_at`, `certified_at`, `attested_at`, `published_at`, `closed_at`, `needs_analysis_completed_at`, and the clock endpoint's `current_utc`), and that logical-clock-stamped timestamps therefore always render `.000` fractional digits (e.g. `2026-11-29T00:00:00.000Z`) — `implementation/util.py:17-22` (`fmt_dt`, the sole serializer), `implementation/util.py:107-119` (`view`, applied to every entity response), `implementation/response.py:22-28` (`api_request_timestamp`), `implementation/routes/ops.py:28` (`current_utc`).

**Step 7 items that required no PRD edit:**
- `test_helpers/fixtures.py` `complete_state_insurance_course(rep_id→rep)` — pure fixture bug (NameError masquerading as 6 state-CE failures); neither PRD nor implementation involved.
- Implementation fixes: none were applied; license counters, carryover cap 6, void reconciliation, and +120d/+30d deadline arithmetic were already pinned verbatim in PRD §3.8/§3.5 and matched the impl.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
- **Edit 1 (§2.2 timestamp-rendering bullet)**
  - (a) **Subject:** wire serialization format of every timestamp emitted by the server (the choice behind both Step 7 test fixes: `completed_at` in `test_06`, `due_at`/`lapse_after` in `test_10`).
  - (b) **Impl paths enumerated and read/grepped:** `util.py:17-22` (`fmt_dt` — only datetime serializer; exactly three fractional digits via `strftime` + `microsecond//1000`); `util.py:25-40` (`parse_dt` — all client-supplied timestamps second-truncated, so no verbatim echo path exists); `util.py:107-119` (`view` — every datetime field of every record passes through `fmt_dt`); all 60+ response sites across `routes/representatives.py`, `contents.py`, `sessions.py`, `enrollments.py`, `assignments.py`, `plans.py`, `attestations.py`, `products.py`, `licenses.py`, `blackouts.py`, `ops.py` (every one is `success(view(...))`, `success(counts)` for the sweep, or `success({"current_utc": fmt_dt(...)})`); `response.py:22-28` (`api_request_timestamp` via `fmt_dt` on the wall clock); every clock-stamping site — `db.py:51-67` (`base_record`/`touch` → `created_at`/`updated_at`), `routes/assignments.py:37` (`due_at`/`lapse_after` from `clock_now()`), `routes/enrollments.py:106,224` (`expires_at`), `routes/plans.py:121,140,173` (`needs_analysis_completed_at`/`published_at`/`closed_at`), `routes/attestations.py:58` (`attested_at`), `services.py:313,334,349,440` (`completed_at`/`certified_at`/`launched_at`) — all fed by `clock_now()`, which is always second-precision (`db.py:36` initial clock microsecond=0; `clock_set` receives only `parse_dt` output).
  - (c) **Wording adjustments made:** (i) scoped the universal claim to *format only* ("rendered in this same format") rather than clock source, because `api_request_timestamp` is deliberately wall-clock (`response.py:23-24`) — a "all timestamps come from the logical clock" claim would have been a new mismatch; (ii) scoped the `.000` clause to "every timestamp stamped from it [the logical clock]" rather than "every timestamp", since `api_request_timestamp` can carry non-zero milliseconds; (iii) used a non-exhaustive "such as" field list under the universal "every timestamp the server emits" claim so unlisted datetime fields (e.g. audit `created_at`) are covered, not excluded; (iv) deliberately did **not** pin input-side second-truncation of client-supplied timestamps — no Step 7 fix exercised that path, so it falls outside the hard scope, and the universal three-digit output rule already keeps `start_at`/`end_at`/`period_start`/`period_end` rendering consistent with the impl.

## Step 9: Complete PRD — 2026-08-15T00:00:00.000Z

The patch is complete and verified. Final summary:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1980_securities_continuing_education_firm/workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md 367 lines / 60,186 chars → PRD_COMPLETED.md 369 lines / 62,558 chars (+2 lines, +2,372 chars; 19 hunks, all in-paragraph — no new sections).

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions.

### Ambiguity pins
- §2.1 — revise — ambiguity — header check rejects missing *or empty* `X-User-ID`/`X-User-Role` — middleware.py:21-25
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the host wall clock; the logical clock governs entity timestamps and deadline comparisons only — response.py:22-28
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` yield `ERR_INVALID_REQUEST` (400) — response.py:61-78
- §2.3 — insert — ambiguity — list ordering tie-break: same-second `created_at` records ordered by insertion sequence — routes/representatives.py:72 (and identical pattern in all list endpoints)
- §2.4 — insert — ambiguity — supplied ISO 8601 instants without an offset are interpreted as UTC and truncated to whole seconds on ingestion — util.py:25-40
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — db.py:51-60
- §2.6 step 4 — insert — ambiguity — field-type shape rules: decimal hour fields accept JSON numbers or numeric strings; whole-number fields must be JSON integers except completion `score` which also accepts integral-valued JSON numbers; flags must be JSON booleans; required strings non-empty (free-text `analysis_notes` excepted) — util.py:43-78, enrollments.py:176-182, plans.py:112-115
- §2.6 (after chain) — insert — ambiguity — unrouted path/method → `ERR_NOT_FOUND` (404); body not parseable as a JSON object → `ERR_INVALID_REQUEST` (400); absent body treated as empty object — app.py:27-39, middleware.py:40-47
- §2.8 — insert — ambiguity — hour values render in JSON as numbers, integral values without a fractional part (`12`, not `12.0`) — util.py:96-104
- §2.9 — insert — ambiguity — pinned `entity_type` vocabulary (`Representative`, `TrainingContent`, `Enrollment`, `RegulatoryAssignment`, `FirmElementPlan`, `AnnualAttestation`, `ProductOffering`, `ProductCertification`, `EnforcementSweep`), sweep events carrying a freshly minted `entity_id` — services.py:155-161, 533-540
- §3.4 — revise — ambiguity — named `ERR_SESSION_NOT_SCHEDULED` for the session-still-SCHEDULED guard at enrollment start — enrollments.py:152-156
- §3.6 — insert — ambiguity — publishing a plan not in `NEEDS_ANALYSIS` yields `ERR_PLAN_NOT_NEEDS_ANALYSIS` — plans.py:130-132
- §3.6 — insert — ambiguity — non-integer `plan_year` list filter matches no plans (empty page, not an error) — plans.py:84-89
- §3.7 — insert — ambiguity — every `cert_status` change (including termination/retire/withdraw/void suspension cascades) writes a `CERTIFICATION_STATUS_CHANGED` event — services.py:155-161
- §3.7 — revise — ambiguity — reinstatement leaves `certified_at` as originally stamped — products.py:141-143

### Mismatch revisions
- §2.6 step 4 — revise — mismatch — "an enrollment create carries exactly one of `content_id` or `session_id`" → "at least one" (impl accepts both when they agree; the match check lives at step 10) — enrollments.py:66-70, 99-101
- §3.4 — revise — mismatch — "supplying neither, or both, is rejected" → "supplying neither is rejected" (both are accepted when `content_id` matches the session's content, as the same paragraph's later sentence already stated) — enrollments.py:66-70
- §3.8 — revise — mismatch — dropped "two-letter" qualifier on `state_code` (impl enforces only a non-empty string) — licenses.py:30
- §4 table — revise — mismatch — `POST /enrollments` description "exactly one of content or session reference" → "content or session reference per delivery format; both accepted when they agree" — enrollments.py:66-101

Everything else in the implementation — state machines, guard ordering per the §2.6 chain, seat invariant (ENROLLED/IN_PROGRESS/COMPLETED hold seats), 90-day validity, 120+30-day assignment windows, 3-attempt budget, required-hours formula (12/16 base, +2/launch-year product capped at 3, minus prior excess, floor 6), license counters (strict/effective with 6h carryover cap, per-course half-up-to-half reported hours), sweep phase order and boundary inclusivity, audit actor `system` for sweep events — was already uniquely pinned by PRD_FINALIZED.md and required no change.
