# Worklog — task_0115_university_registrar

## Step 1: Create Task Directory — 2026-06-03T02:31:27.000Z

Created `tasks/task_0115_university_registrar/workspace/` (pre-assigned directory; auto-increment scan skipped per orchestrator directive).

## Step 2: Generate Scaffold — 2026-06-03T02:59:13.000Z

Everything is structurally sound. All three files are written, lint-clean, and self-consistent:

- File split honored (no design keys leaked into SCAFFOLD.yaml; each design file has exactly one top-level key).
- §1.8: 19 instances across all 9 difficulty rules (≥2 each).
- §1.9: 37 instances (35 active + 2 `excluded_because` stubs referencing valid §1.8 instances) spanning all 8 applicable claim-extraction-guide sections.

All verification gates pass: clean lint, no forbidden concurrency vocabulary, every error code triggerable, no unproduced enum values, unique instance names, all `excluded_because` references valid.

### Summary

Generated the Expert-difficulty scaffold for **task_0115_university_registrar** (University Registrar & Course Registration). All three files written:
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`

**Final counts:**
- **Entities: 12** (Term, Student, Program, Course, CourseRequirement, Instructor, Section, EnrollmentAppointment, Enrollment, Hold, SwapRequest, RefundTransaction) — within Expert 10–15 band.
- **Endpoints: 45** — over the Expert 20–32 band, forced by FK reverse-reachability (20 FKs across 12 entities → 13 discovery GETs, each sole coverer of its FK). Per `expert_endpoint_band_vs_fk_reachability` guidance, overage accepted because scaffold is lint-clean.
- **Error codes: 26** — within Expert 18–30 band.
- **Calculation variants: 5** (`enrollment_refund` ×3, `cumulative_gpa` ×2) — exceeds 3+ directive.
- **State machines: 5** (Term, Section, Hold, SwapRequest, Enrollment) — meets 4+; non-linear via Enrollment's parallel `registration_status × grade_status` axes, Section's OPEN↔CLOSED cycle, SwapRequest's COMMITTED/ABORTED fork.

**Design archetype:** quota/allocation (seat/waitlist) blended with graph-constraint (prereq/coreq DAG), optimistic concurrency (OCC seat-grab on `Section.version`), cascading side effects (section-cancel → drop → refund → owed; drop → waitlist promotion → tuition charge), threshold triggers (deadline/refund tiers), derived-field reconciliation (GPA, earned credits, tuition owed).

**Verification:** `scaffold_lint.py` → clean lint (641 calls across 19 §1.8 + 35 §1.9 instances; all 20 FKs reverse-reachable). All nine §0.5 difficulty rules satisfied with ≥2 instances each. One bug fixed during generation: `tuition_owed` formula corrected to include {ENROLLED, WITHDRAWN, DROPPED} in charged sum so a full-refund drop nets to exactly 0.

## Step 3: Copy Shared Files — 2026-06-03T02:59:43.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T03:05:58.000Z

**File written:** `workspace/PRD.md` (281 lines). Did NOT read either design YAML.

**Major sections produced:**
- **§1 Introduction** — business context + role overview + contract scope
- **§2 Global Specifications** — RBAC (per-role identity translation), API Response Structure (verbatim §2.2), Pagination, Common Resource Properties & Versioning, OCC on Section Seats, Temporal Evaluation & Logical Clock, Monetary/Credit/Precision, Hierarchical Existence & Reverse-Reachability, Cascades & Derived-Field Reconciliation
- **§3 Business Logic** — 11 subsections: catalog/term setup, sections & instructor conflict rule, students/appointments/holds, registration (enroll vs waitlist), drop/withdraw/promotion, section-cancel cascade, refund calculation, grading/GPA/standing, tuition/transcript/degree-audit, atomic swap, validation order
- **§4 Endpoint Definitions** — 45-row table
- **§5 Error Code Catalogue** — 26-row table

**Hard Contracts — all PASS:** field coverage (60/60 entity fields, 48 endpoint inputs), rule coverage (validations ordering, OCC, 5 state machines incl. parallel grade axis, 5 calculations, cascades, sibling-branch symmetry), path purity (0 path tokens in §3). §2.2 canonical body present byte-for-byte.

## Step 5: Generate Unit Tests — 2026-06-03T03:28:42.000Z

Both directories written: `test_helpers/` (9 files) and `test_suite/` (conftest + 6 test files).

**Test files:** 6 — `test_01_catalog_and_entities.py`, `test_02_enrollment_gates.py`, `test_03_enrollment_corner_gates.py`, `test_04_refunds_and_tuition.py`, `test_05_grades_gpa_transcript.py`, `test_06_lifecycle_cascades_swaps.py`

**Total test functions:** 73 — all passing against the unit-test-generator's OWN reference implementation under `--isolation per-test-server` (73/73).
- **Queue A (Difficulty):** 38 tests covering all 19 instances across all 9 rules, every instance ≥2 tests.
- **Queue B (Corner):** 35 tests covering all 35 non-stub instances (≥1 each).
- **Skipped:** none testable; only the 2 `excluded_because` stubs not translated (owned by their referenced Difficulty instances).

**Key finding — pre-computation bug in difficulty design index:** `Difficulty/dual_variant_calc/gpa_cumulative_vs_term_scope` asserted `term_gpa == 4.00` but its own setup grades both A(4cr) and B(3cr) into Term A; PRD credit-weighted term formula yields (16+9)/7 = 3.57. Kept the PRD-uniquely-derivable cumulative GPA 2.50 assertion and corrected term_gpa literal to 3.57. Two test-helper bugs fixed during validation (wrong-arity `add_course_requirement`; instructor double-booking / appointment-window collisions in multi-section grading fixture). No skip/xfail markers remain.

## Step 6: Generate Implementation — 2026-06-03T03:28:42.000Z

Complete Python + Flask implementation in `workspace/implementation/`.

**File list:** `start.sh`, `requirements.txt` (flask==3.0.3), `app.py`, `db.py`, `errors.py` (26-code catalog), `middleware.py` (auth/RBAC/pagination), `response.py` (§2.2 envelope), `routes/` (terms, programs, courses, instructors, sections, students, appointments, enrollments, holds, swaps, clock), `services/` (clock, entities, serialize, helpers, core calculations/reconciliation, enroll lifecycle/cascade/swap).

**Launch:** Flask 3.0.3, one blueprint per resource group. `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` foreground; pip install guarded by `if ! python3 -c "import flask"` so concurrent per-test reboots don't flake.

**Storage:** in-memory dicts keyed by id in `db.py` + logical-clock dict. No seeding — every store empty at module load; monotonic `_seq` breaks created_at ties for deterministic ordering. State wiped on each fresh process.

**Correctness verified (smoke):** response envelope, immutable entities omit updated_at/version, validation-order precedence, enroll/waitlist routing, OCC ERR_STALE_VERSION (412), gates (duplicate/credit-limit/hold/appointment/section-open/waitlist-full), instructor double-booking buffer vs student plain-overlap, drop/withdraw windows + refund tiers (round-half-up Decimal cents), waitlist promotion tuition charge, section-cancel cascade (FULL refund regardless of clock), GPA/standing/earned-credits recompute, transcript, degree-audit, atomic swap (COMMITTED/ABORTED), prereq/coreq enforcement. Withdraw sets `letter_grade="W"` with `grade_status=UNGRADED`, excluded from GPA/credits/prereq/audit.

## Step 7: Run Tests and Iterate — 2026-06-03T04:01:18.000Z

**Outcome: all 73 tests pass; confirmed stable across 48 consecutive post-fix rounds (6 × 8-round sweeps) plus 96/96 isolated boot-stress. 0 test deletions, 0 test_suite assertion changes. 2 transport/launch-resilience fixes (1 test_helpers, 1 implementation). No PRD-business behavior changed.**

The long-lived Step 7 subagent exited reporting a clean 8/8 sweep with 0 fixes. On orchestrator re-runs, **two distinct intermittent flakes surfaced** that the subagent's single (lucky) sweep had missed — exactly the flakiness the 8-round design targets. Both were diagnosed to the harness's per-test-server restart model (kill + relaunch on the SAME fixed port before every test), not to implementation business logic. Every boot the server took, it passed 73/73; the failures were transport/boot races at the restart boundary.

### Flake A — stale keep-alive connection (status `failed`)
- **Signature:** `requests.exceptions.ConnectionError: ('Connection aborted.', BadStatusLine('POST /courses ...'))` (also seen on `POST /sections`), always on the FIRST request a test issues after a restart. Victim test varied (`test_instructor_sections_outside_buffer_allowed`); rate ~1 per 16–24 rounds.
- **Root cause:** `GenericApiClient` (shared runner lib) uses a persistent `requests.Session()`, and `test_helpers/api_client.py` exposes it as a module-level singleton living for the whole pytest process. Per-test-server isolation kills+relaunches the server on the same port between tests; a keep-alive socket pooled in a prior test points at the dead server. urllib3's `is_connection_dropped` has a race window right after the kill where the stale socket still looks alive, so the request is written to a dead connection and returns garbage. requests' default adapter does 0 retries, so the `ConnectionError` propagates. Confirmed NOT a server crash: the impl's catch-all `@app.errorhandler(Exception)` returns a JSON 500, never a dropped connection.
- **Fix (test_helpers/api_client.py):** `ApiClient.__init__` now sets `session.headers["Connection"]="close"` (minimizes pooling) and overrides `_request` to retry once on `requests.exceptions.ConnectionError` after `session.close()` (drops stale sockets, retries on a fresh connection). Safe + non-masking: the failed request never reached the live server, and a real server error returns an HTTP 4xx/5xx response (not a ConnectionError), so no implementation fault can be hidden. No payload/identity/assertion semantics changed.

### Flake B — boot bind-race (status `error`, "could not be restarted")
- **Signature:** `Failed: API server ... could not be restarted before test_enrolled_credit_hours_visible_immediately` with ~15.6s duration (the runner's 30×0.5s restart poll fully exhausted). Rate ~1–2 per ~24 rounds, only under 8× concurrent sweep load.
- **Root cause:** on relaunch on the same port immediately after the prior server's `kill -9`, the old listener socket can linger a few ms, so the fresh `python3 app.py`'s initial `bind()` transiently fails with "Address already in use" and the process exits — the runner then polls a port nothing is listening on until the 15s window expires. (Distinct from the 5s macOS `getfqdn` boot stall, which the runner's injected `_dnsboot` sitecustomize already neutralizes — verified: boot is 0.27s with dnsboot vs 5.2s without; dnsboot loads reliably.)
- **Fix (implementation/workspace/implementation/app.py):** wrapped `app.run(...)` in the `__main__` block in a ≤10s bind-retry loop that catches `OSError` and retries every 0.2s, so a fresh boot survives a transient port-in-use during rapid restart instead of crashing. Launch resilience only — traces to the INSTRUCTION boot contract ("boot cleanly from a fresh process on every invocation"); adds NO endpoint/field/validation/side-effect and cannot change any API response.

### Validation
- Pre-fix: ~3 flaky rounds observed across ~24 rounds (mix of A and B).
- Post-fix: **48/48 rounds clean** (6 consecutive 8-round sweeps), plus a separate 96/96 isolated kill→spawn→poll boot-stress (max boot 0.5s). Final canonical `results.{1..8}.json` regenerated from a clean sweep — all 73/73.

### Diff summary (for Step 8 hand-off)
- **Tests deleted:** none.
- **test_suite/ fixes:** none (no assertion, precondition, payload, or identity changed).
- **test_helpers/ fixes:** `api_client.py` — `ApiClient.__init__` adds `Connection: close`; new `ApiClient._request` retries once on `requests.exceptions.ConnectionError`. Transport-only; fixes the stale-keep-alive race across per-test-server restarts.
- **implementation/ fixes:** `app.py` (`__main__`) — bind-retry loop around `app.run` to survive transient "Address already in use" during same-port restart. Launch-resilience only; no API behavior change. **No business-logic, endpoint, field, validation, calculation, or state-machine change was made anywhere in `implementation/`.**

## Step 8: Finalize PRD — 2026-06-03T04:04:06.000Z

`PRD_FINALIZED.md` created, **byte-identical to `PRD.md`** (281 lines, 0% delta; `diff` clean). **0 substantive edits — both Step 7 fixes are transport/launch-resilience pinning no API behavior.**

Per-item evaluation:
- **Item 1 (test_helpers/api_client.py):** `Connection: close` + retry-once-on-ConnectionError live entirely in the test client's HTTP transport; no payload/identity/precondition/assertion altered; a real server error returns an HTTP response (not a ConnectionError) so the retry cannot mask faults → no PRD edit.
- **Item 2 (implementation/app.py `__main__`):** bind-retry loop wraps `app.run` only; `create_app()`, blueprints, error handlers, stores, routes, and business logic untouched; adds no endpoint/field/validation/calculation/transition/side-effect → no PRD edit.

No NO-NEW-MISMATCH searches triggered (rule fires per committed edit; 0 edits). Expected/valid outcome given both fixes pin no API-visible business behavior.

## Step 9: Complete PRD — 2026-06-03T04:09:21.000Z

`PRD_COMPLETED.md` created from `PRD_FINALIZED.md`. Lines 281 → 281 (all edits in-paragraph); chars 42,794 → 44,172 (+1,378). **6 changes: 3 ambiguity-pins, 3 mismatch-revisions.**

- **§2.4 Versioning** — revise — mismatch — PRD claimed every derived-field recompute bumps `updated_at`/`version`; impl only bumps when the value actually changes (no-op recompute leaves both untouched). — `services/core.py:65-72,111-120,148-150`; `services/entities.py:39-48`
- **§2.5 OCC** — revise — mismatch — PRD said registration is the only endpoint taking a version field; the atomic swap also carries `expected_section_version` with the same `ERR_STALE_VERSION`/412 guard. — `routes/swaps.py:27`, `services/enroll.py:349-350`
- **§2.6 Logical Clock** — insert — ambiguity — clock-set response was unspecified; impl returns 200 `data:{"now_iso8601": <value>}`, rejects unparseable instant with `ERR_VALIDATION`. — `routes/clock.py:24-30`
- **§3.8 Grading** — revise — mismatch — non-`ENROLLED` status and term-not-`IN_SESSION`/`CLOSED` both yield `ERR_INVALID_STATE` (evaluated before already-graded/grade-validity); `ERR_ALREADY_GRADED` reserved for already-`GRADED`. — `services/enroll.py:239-246`
- **§3.9 Transcript** — insert — ambiguity — `lines` shape/ordering/term-scoping + `earned_credit_hours` scope pinned: each line = full serialized graded enrollment, `created_at` asc, term-restricted when `term_id` given; `earned_credit_hours` always cumulative. — `routes/students.py:174-198`
- **§3.9 Degree Audit** — insert — ambiguity — `satisfied_course_ids` pinned to distinct ids sorted ascending. — `routes/students.py:215-226`

Default values, validation bounds, refund tiers, waitlist routing/promotion, cascades, ownership/RBAC were already uniquely pinned and matched impl — left unchanged. The two Step-7 launch/transport fixes correctly produced no PRD prose.

---

## PIPELINE COMPLETE — 2026-06-03T04:09:21.000Z

All 9 steps done. Final state: **73/73 tests pass, stable across 48 consecutive post-fix rounds + 96/96 boot-stress.** Artifacts present: SCAFFOLD.yaml (+ 2 design YAMLs), workspace/PRD.md, PRD_FINALIZED.md (≡ PRD.md), PRD_COMPLETED.md (6 pins), test_helpers/, test_suite/, workspace/implementation/ (+ results.{1..8}.json all green).
