# Worklog — task_1380_patient_grievance_complaint_resolution

## Step 1: Create Task Directory — 2026-08-13T02:41:00.000Z

Task directory `tasks/task_1380_patient_grievance_complaint_resolution/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker; Step 1 treated as DONE (no index scan performed, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-13T03:39:00.000Z

## Task complete: task_1380_patient_grievance_complaint_resolution

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1380_patient_grievance_complaint_resolution/`):
- `SCAFFOLD.yaml` (§1.0–1.7; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

**Counts**
- Entities: 18 | State machines: 13 (incl. parallel `regulatory_clock_status` dimension and posture machine) | Calculations: 13 | Validations: 17 (priorities 1–10 across auth/existence/state/safety/referential/constraint/temporal/fiscal) | Endpoints: 84 | Errors: 65 | Roles: 7 (4 entity-backed StaffMember roles + 3 opaque; segregation-of-duties model)
- §1.8: 24 instances across all 9 rules (2–3 each), 100% structured recipes
- §1.9: 60 instances (52 full recipes + 8 `excluded_because` stubs), spanning all 9 guide sections
- Lint: **VERDICT: clean lint** (866 calls scanned; all §1.8/§1.9 calls conform to §1.5; all FKs reverse-reachable). Verdict block pasted verbatim in the run above.

**Beyond-expert difficulty design decisions**
- **Dual-variant calcs on different domains**: calendar-vs-business regulatory due dates on PatientCase (verified literals: 2026-09-06 vs 2026-09-21 around a holiday); headcount-vs-exposure-weighted breach rates on TrendSnapshot (5000 vs 1000 bp on identical closures).
- **Combinatorial formulas in all three modes**: (a) 4-input clamped priority score (raw 103 → 100), (b) pinned nested rounding order for system trend rate (per-cell round → 4167 bp, not the forbidden global 4000), (c) tolling→due→status evaluation order pinned to break the circular-looking dependency.
- **Non-linear machines on 3 entities**: PatientCase reopen cycle + parallel clock dimension; ResponseLetter revision loop (version-literal 5 after one loop); QualityRiskEscalation fork-join (BOTH-track join gates adjudication).
- **Transitive cascades from different triggers**: satisfaction score ≤2 → 4-link reopen cascade (follow-up→case→investigation+letter→due re-anchor+unit counter); substantiated adjudication → cosign/expedite recompute → breach re-eval → auto-created ReportableEvent.
- **OCC true races** (both pass §1.2.1's serial-observability filter): classification supersede and PRIMARY-assignment supersede, both guarded by `expected_case_version` with 412.
- **Boundary arithmetic**: exact-deadline ON_TIME vs +1s LATE; 50000-cent cap equality allowed vs +1 rejected; 3rd-grievance systemic trigger; 900s interview-buffer inclusive boundary; half-open rounding adjacency; ack-deadline strict->.
- **RBAC depth**: segregation-of-duties on three independent step pairs (findings/approve, file/adjudicate, issue/approve recovery), entity-backed capability gating, identity-match checks, QRO co-sign conditional on computed `requires_qro_cosign`.
- **Cross-entity gates on 3 distinct pairs**: letter↔escalation, investigation↔assignment, case↔unit posture (with late-filing → RESTRICTED → blocked-restore chain).

**Notable fixes during generation**: removed unreachable `ERR_INVESTIGATION_ALREADY_EXISTS` (state check always fires first — found during corner-design replay); added `ERR_ROOM_INACTIVE` to close a trigger↔validation gap; all asserted arithmetic literals (due dates, bp rates, credit seconds, priority scores) were computed by hand from the pinned formulas and calendar lattice (Aug 2026, 2026-08-01 = Saturday = clock default).

## Step 3: Copy Shared Files — 2026-08-13T03:39:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1380_patient_grievance_complaint_resolution/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T04:05:00.000Z

PRD generation is complete and all three hard contracts pass. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1380_patient_grievance_complaint_resolution/workspace/PRD.md` — 389 lines.

**Section list:**
- §1 Introduction (2 paragraphs, regulatory-obligation angle)
- §2 Global Specifications (11 subsections): 2.1 RBAC with full role-identity translations, 2.2 API Response Structure (**byte-identical** to the canonical `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Logical Clock (startup default 2026-08-01T00:00:00Z), 2.5 Common Resource Properties (incl. the three `common_fields: false` entities), 2.6 Validation Precedence (15-rung ordered ladder incl. the schema-last / missing-fields-before-FK nuance), 2.7 OCC, 2.8 Calendar vs Business-Day Arithmetic, 2.9 Money/Duration/Basis-Point Precision, 2.10 Segregation of Duties, 2.11 Resource Resolution (all 18 not-found IDs enumerated)
- §3 Business Logic (9 subsections): organizational setup → intake/classification → assignment/investigation → written response/closure → clock suspensions/tolling/breach derivation → escalations → reportable events/unit posture → service recovery/rounding → follow-up/reopen/withdrawal/trends
- §4 Endpoint table: 84 endpoints, 4 columns only
- §5 Error catalogue: 65 errors, 2 columns only

**Contract reports:**
- Contract 1 (Field-Name Coverage): 121 required tokens (all `entities[].fields[].name` + every endpoint `input`/query/path identifier), 121 present, 0 missing — PASS, verified in two passes.
- Contract 2 (Rule Coverage): validation priority ordering 15/15 expressed in §2.6; OCC rules 2/2 (both write endpoints named with `expected_case_version` + `ERR_STALE_VERSION`/412 + before-business-rule ordering); state-machine transitions 70/70 across all 13 machines (incl. 9 withdraw siblings, parallel clock dimension with precedence note, fork-join review, 3-link reopen and adjudication cascades); calculations 13/13 in reconstruction-safe prose (due windows 30/7/3/15/7, interval-merge tolling, pinned derivation order, priority score 20/35/50+15+urgency+10·reopen cap 100, selector ranking with `created_at` tiebreak, both basis-point variants with pinned per-cell rounding, systemic threshold exactly-3, 50,000-cent cap strict-greater, 48h/5-business-day deadlines, 900-second buffer, half-open rounding overlap); all 65 error IDs matchable to trigger conditions in §2/§3; endpoint side effects 84/84 — PASS.
- Contract 3 (§3 Path Purity): 689 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path tokens — PASS.

**Zero-Silence-Rule adjudications:**
1. `outstanding_recovery_cents` tension — the entity defines it as sum of `ISSUED` values minus sum of `REVOKED` values, while transition side effects say approve adds / revoke subtracts one value (under status-transition semantics these diverge). Rendered both statements verbatim in §3.8 without inventing a reconciliation.
2. Explicit-investigator capability precondition (`CLASSIFIED → ASSIGNED`) names no error ID in the scaffold (unlike `ERR_ADVOCATE_ON_LEAVE` / `ERR_INVESTIGATOR_AT_CAPACITY`); PRD states the `INVESTIGATOR`-capability requirement without binding an invented error.
3. Adjudicate's `outcome` payload has no declared value set anywhere in the scaffold (only `ERR_INVALID_ENUM` lists it); PRD describes it as selecting between substantiated and unsubstantiated findings without inventing literal enum strings.
4. Reclassification state scope: PRD states exactly the scaffold's two restrictions (no decisions on `CLOSED`/`WITHDRAWN`; `GRIEVANCE → COMPLAINT` only in `INTAKE`/`CLASSIFIED`) without adding further constraints.
5. `review_track` duality (entity says "required at triage"; manual-create endpoint also accepts it): rendered as accepted at manual filing and stored/required at triage, consistent with both.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate Unit Tests — 2026-08-13T05:10:00.000Z

Generation complete. Full audit is green.

## File inventory

**`test_helpers/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1380_patient_grievance_complaint_resolution/test_helpers/`)
- `types.py` — 17 entity TypedDicts (append-only `ClassificationDecision`/`InvestigationNote`/`HolidayObservance` correctly omit `updated_at`/`version`), all status/enum vocabularies, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (all 60+ routes incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` (53 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` shape checkers; append-only entities assert absence of `version`/`updated_at` keys
- `factories.py`, `constants.py` — input-field payload factories; domain thresholds (cap 50000, buffer 900s, windows 30/7/3/15, etc.)
- `test_users.py` — shared constants for opaque roles; `make_{advocate,investigator,qro,director}_headers(staff_id)` builders for the four entity-backed roles (identity threading enforced in fixtures)
- `fixtures.py` — tiered composites: `setup_classified_case` → `setup_assigned_case` → `setup_open_investigation` → `setup_findings_submitted` → `setup_response_drafting` / `setup_complaint_response_drafting` → `setup_letter_in_review` → `setup_letter_approved` (CRITICAL auto-routes to QRO co-sign + 7-section letter) → `setup_closed_case` / `setup_closed_complaint`; escalation drivers to `REVIEWS_COMPLETE`
- `__init__.py` — barrel export

**`test_suite/`** — `conftest.py` + 8 files, **96 test functions**, organized by concern: `test_01` envelope/pagination/intake RBAC, `test_02` classification/clock/dues/OCC/systemic sweep, `test_03` assignment/investigation/booking, `test_04` letter loop/approval gates/closure, `test_05` reopen/withdraw/follow-up, `test_06` escalations/events/posture, `test_07` recovery ledger/rounding, `test_08` tolling/trends/priority.

## Per-queue counts

- **Queue A (Difficulty): 22 of 24 instances emitted, each with exactly 2 tests (44 tests).**
- **Queue B (Corner): 51 of 52 non-stub instances emitted (52 tags — the envelope instance legitimately got 2 tests for its success+error halves).** All 8 `excluded_because` stubs skipped untranslated; their `difficulty_instance` pointers all resolve.
- **Every test's docstring ends with exactly one verbatim `Design:` line; all 135 quoted PRD citations survive literal grep of PRD.md; no skip/xfail anywhere.**

### Skipped instances (PRD-first filter failures)

1. `Difficulty/priority_pair_validation_conflict/withdrawn_case_over_cap_recovery_state_beats_fiscal` — the PRD never states that recovery-action creation is gated on case lifecycle state (§3.8 is silent; §2.6 rung 6 is generic), so the asserted `ERR_CASE_INVALID_STATE` on a WITHDRAWN case is not uniquely derivable; the whole priority-pair claim collapses without the state leg.
2. `Difficulty/priority_pair_validation_conflict/cancelled_letter_self_approve_state_beats_sod` — the withdraw cascade leaves case WITHDRAWN + letter CANCELLED, so both the case-lifecycle guard (§2.6 rung 6) and the letter-state guard (rung 7) fail simultaneously; §2.6's global ladder order conflicts with §3.4's endpoint-level "gates are evaluated in order" listing (letter first), so the asserted winner `ERR_LETTER_INVALID_STATE` is not uniquely derivable.
3. `Corner/state_machines/letter_issue_before_approval_rejected` — same root cause: letter and case states move in lockstep (DRAFT↔RESPONSE_DRAFTING … APPROVED↔PENDING_CLOSURE), so `ERR_LETTER_INVALID_STATE` on issue is unreachable in isolation; the DRAFT-letter fixture also violates the case guard, and the asserted winner is ambiguous between rung 6 and §3.4's ordering.

### Notable design decisions

- **Fixture corrections (assertions untouched, recipe intent preserved):** three instances (`tolling_recompute_precedes_status_derivation`, `patient_case_reopen_cycle_with_parallel_clock`, `tolling_disjoint_suspensions_sum_and_duplicate_open_rejected`) asserted `ON_TRACK` readings for grievances whose acknowledgment was never recorded — PRD §3.5 uniquely derives `ACK_BREACH` there (ack clock is not tolled). I added the natural `acknowledge` call inside the 7-day window so every asserted value is PRD-derivable. For `investigation_requires_active_primary_assignment`, the recipe's CLASSIFIED-case fixture would hit `ERR_CASE_INVALID_STATE` (case must be ASSIGNED, checked first); I reach "ASSIGNED with no ACTIVE PRIMARY" via a SUPPORTING-only assignment, which isolates `ERR_NO_ACTIVE_PRIMARY_ASSIGNMENT` exactly.
- **Version assertions made relative:** PRD §2.5 never pins the initial version value, so the letter-loop test asserts `final == created + 4` (four mutations × +1) and the case-create test asserts version presence/type only, instead of the recipes' absolute `== 5` / `== 1`.
- **Assignment-in-ASSIGNED reading:** several instances (supersede, duplicate-assignment) require assignment creation to be accepted while the case is ASSIGNED. PRD §3.3's "must be in CLASSIFIED" sentence would make the same section's supersede semantics dead code, so the only PRD-consistent reading permits it; tests exercise exactly that.
- **Recovery ledger:** asserted via the two operational sentences ("raises by its value" / "falls by the action's value"), which pin issue+revoke netting to zero; the formula sentence read literally would double-subtract and contradict them.

## Step 6: Generate Implementation — 2026-08-13T05:10:00.000Z

Everything verified. The implementation is complete and all smoke suites pass under fresh-process boots.

## Summary

**File inventory** of `/home/ubuntu/github/CodingPRD/tasks/task_1380_patient_grievance_complaint_resolution/workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` | Foreground launcher: `.deps_ok`-guarded install, `exec python3 app.py` |
| `requirements.txt` | `flask>=2.2` |
| `app.py` | Flask entry, error handlers, `POST /_clock/set_current_utc`, blueprint registration; binds `0.0.0.0:$PORT` (default 10000) |
| `clock.py` | Logical clock (startup default exactly `2026-08-01T00:00:00Z`, never wall-clock), ISO-8601 parse/format (3 fractional digits), holiday-aware business-day arithmetic |
| `db.py` | 18 in-memory dict stores + creation-order sequence; verified empty after full app import (no seeding anywhere) |
| `errors.py` | `ApiError` + all 67 catalog error IDs |
| `response.py` | Envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data{error_id, message}` |
| `middleware.py` | Header auth (`X-User-ID`/`X-User-Role`), 7 roles, entity-backed capability check (ADVOCATE/INVESTIGATOR/QRO/DIRECTOR → StaffMember) |
| `helpers.py` | Enum domains, body/pagination validators, common-quartet stamps, all 18 serializers |
| `derived.py` | Derived-on-read engine: interval-merged tolling credit, calendar/business dues from stored anchors, pinned `regulatory_clock_status` derivation, priority score, counters, follow-up expiry, filing deadlines |
| `cascades.py` | Closure, withdraw, reopen (3-link), systemic-threshold sweep, substantiation expedite cascade |
| `routes_org.py`, `routes_cases.py`, `routes_investigations.py`, `routes_letters.py`, `routes_recovery.py`, `routes_risk.py`, `routes_rounding.py`, `routes_closure.py` | 8 route modules |

**Endpoint coverage: 84/84** — orchestrator independently counted PRD §4 table rows (84) and Flask `@route` decorators in implementation/ (84); subagent's self-reported "76/76" was a miscount of its own coverage. Every row of the PRD §4 endpoint table is implemented, including the clock control, timeline read, trend-snapshot compute, and the 204 holiday delete.

**Error-catalog coverage: 67/67** — every error ID in PRD §5 is raised with its catalog HTTP status, ordered per the §2.6 precedence ladder (missing-required-field 400s before dependent-FK existence; OCC at 412 before business rules; safety gates before cross-aggregate before occupancy before temporal before fiscal before schema).

**Verified behavior** (5 smoke suites, ~140 assertions, each against a fresh boot): full grievance pipeline to closure, reopen loop with letter supersession and +15-day re-anchoring, suspend/tolling/breach derivation (SUSPENDED masking, RESPONSE_BREACH precedence, boundary equality ON_TIME), recovery self-approval + 50,000-cent cap (strict `>`, re-check at approve), rounding overlap/capacity, 900-second booking buffer (899 rejected, 900 allowed), late-filed event → unit RESTRICTED → restore gating, systemic sweep at exactly 3, trend snapshots (5000 bp headcount, 333 bp exposure-weighted, system rate 2500 bp with per-cell-round-first), withdraw cascade, OCC 412s, RBAC/entity-backed roles.

**Notable design decisions**
- **Anchor-based dues**: each case stores `_cal_anchor/days/offset` and `_biz_anchor/days/offset`; dues = variant base + offset + interval-merged tolling, recomputed on every read — so holiday deletion re-prices business-day dues per PRD §2.8, and the expedite cascade pins the *due* to `adjudicated_at + 7d` via a negative tolling offset.
- **Derived vs stored**: all `source: computed` fields (counts, clock status, priority, outstanding recovery, follow-up due/expiry, event deadline) are derived on read; `late_filing` and `_closure_due_calendar_at` are frozen at the filing/closure instant per the state-machine side effects, insulating trend math from later holiday edits and post-closure expedites.
- **Assignments allowed from CLASSIFIED *and* ASSIGNED** — scaffold OCC rule §1.2.1 explicitly legitimizes a second assignment create (PRIMARY supersede), which is unreachable under a CLASSIFIED-only reading of PRD §3.3.
- **Manual escalation create requires `review_track`** per PRD §3.6's filing narrative (which §4 defers to), even though triage re-stores it.
- Rounding/booking window sanity (rung 11) is deliberately evaluated *after* overlap/buffer (rung 10), per the §2.6 ladder.

## Step 7: Test/Fix Iteration Loop — 2026-08-13T05:25:00.000Z

Eight-round parallel stability sweeps (`prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds) driven to green.

**Sweep 1 (baseline): 57/96 in all 8 rounds — 39 systematic failures, zero flakiness.**
Union diagnosis found three root causes:

1. **test_helpers/fixtures.py — SimpleNamespace duplicate-kwarg TypeError (26 tests).** Seven composite builders (`setup_open_investigation`, `setup_findings_submitted`, `setup_response_drafting`, `setup_complaint_response_drafting`, `setup_letter_in_review`, `setup_letter_approved` ×2 branches, `setup_closed_case`, `setup_closed_complaint`) passed `case=` both inside `**vars(base)` and as an explicit kwarg. Fixed by merging `"case": get_case(...)` into the unpacked dict. Pure test-helper bug; assertions untouched.
2. **test_suite/ + test_helpers/ — timestamp literals missing fractional digits (12 tests blocked directly, ~190 literals).** PRD §2.4: "All timestamps exchanged with the API are ISO 8601 in UTC with three fractional digits." The implementation correctly emitted `.000Z`; the tests' expected literals omitted it. Normalized every `YYYY-MM-DDTHH:MM:SSZ` literal to `.000Z` form (198 literals across 8 test files + factories/constants/fixtures). Date-only (`observance_date`) and `YYYY-MM` period literals untouched; no assertion semantics changed.
3. **implementation/derived.py — `outstanding_recovery_cents` double-subtracted REVOKED (1 test: `test_issue_revoke_pair_nets_to_zero`).** PRD §3.8's two operational sentences ("raises ... by its value" / "falls by the action's value") pin issue+revoke netting to zero; the formula sentence read literally contradicts them. Fixed to sum over currently-`ISSUED` actions only (identical to the operational ledger in all reachable states). Cap math (`issued_value_sum`) already used ISSUED-only, so this also restores internal consistency.

**Sweep 2: 96/96 in round 8; rounds 1–7 each errored on the SAME test (`test_status_reads_off_recomputed_due`) at the SAME wall-clock instant with "server could not be restarted".** Reproduced outside the runner with a faithful 8-port kill/spawn/poll replica: captured server stderr showed `Address already in use` on bind in 9 of 10 failures — a transient local-port squatter (an in-flight connection whose ephemeral local port collides with the just-freed server port during the kill/spawn window) crashed the new server instantly, and the runner's 15s readiness poll then expired.

4. **implementation/app.py — bind-retry on startup.** Replaced `app.run(...)` with `werkzeug.serving.make_server` in a retry loop (0.25s cadence, 120s cap). EADDRINUSE now delays boot by sub-seconds instead of killing the process; serving semantics unchanged (single-threaded, no reloader). No API-contract change.

**Sweep 3: all 8 rounds 96/96, 0 failed, 0 errors — EXIT.**

No tests deleted. No assertions weakened. No PRD-required check removed from the implementation. No seeding/persistence added — storage remains in-memory dicts only.

## Step 8: Finalize PRD — 2026-08-13T05:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1380_patient_grievance_complaint_resolution/workspace/PRD_FINALIZED.md` written with exactly one edit.

**Line counts / %-delta:** PRD.md 389 lines, PRD_FINALIZED.md 389 lines — 0% delta (single in-place sentence revision within one paragraph line).

**Changes:**
- §3.8 — revise — removed the "minus the sum over those currently `REVOKED`" clause from the `outstanding_recovery_cents` formula and added a clarifying sentence that the ISSUED-only sum reproduces the raise-on-issuance / fall-on-revocation netting exactly — `implementation/derived.py:196-208` (cap math cross-check at `implementation/routes_recovery.py:37-42`).

**Diff items evaluated, no PRD edit needed:**
- Item 1 (fixtures duplicate-kwarg TypeError): pure test-helper bug; no behavioral surface.
- Item 2 (timestamp literals): PRD §2.4 already pins "ISO 8601 in UTC with three fractional digits"; implementation (`clock.py:40-43` `iso_ms`) already conformed; tests were wrong. Prose kept verbatim.
- Item 4 (app.py bind-retry on EADDRINUSE): startup mechanics only, no API-contract change; PRD is an API contract document. No edit.

**Per-edit pre-edit search log:**
- Edit 1 (§3.8 outstanding_recovery_cents formula):
  - (a) Subject: the derivation rule for the case's `outstanding_recovery_cents` ledger figure.
  - (b) Impl paths enumerated and read: `implementation/derived.py:196-208` (`outstanding_recovery_cents` — ISSUED-only sum, recomputed per call); `implementation/helpers.py:255-268` (`serialize_case` — exposes the field on every case read); `implementation/routes_recovery.py:37-42` (`issued_value_sum` — ISSUED-only, used by cap check at create line 56 and approve line 136); `routes_recovery.py:45-84` (create: born ISSUED or PENDING_APPROVAL); `routes_recovery.py:118-145` (approve: PENDING_APPROVAL → ISSUED); `routes_recovery.py:148-160` (reject → REJECTED); `routes_recovery.py:163-177` (revoke: ISSUED → REVOKED); `implementation/cascades.py:102-105` (withdraw cascade rejects only PENDING_APPROVAL actions, leaves ISSUED untouched). Also grepped all of `implementation/` for `outstanding_recovery_cents`, `REVOKED`, and `recovery_actions` to confirm no other path mutates or reads the ledger.
  - (c) Wording adjustment: kept the original sentence structure and merely deleted the REVOKED-subtraction clause, then appended one explanatory sentence tying the ISSUED-only sum to the two already-present operational sentences ("raises ... by its value" / "falls by the action's value") — this avoids asserting anything about REJECTED/PENDING_APPROVAL actions beyond what the code does (they simply never enter the ISSUED set), so all enumerated paths including the withdraw cascade remain correctly described.

## Step 9: Complete PRD — 2026-08-13T06:05:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1380_patient_grievance_complaint_resolution/workspace/PRD_COMPLETED.md`.

**Source vs. output:** PRD_FINALIZED.md = 389 lines / 64,501 chars → PRD_COMPLETED.md = 391 lines / 67,503 chars (char-delta +3,002; +2 lines from the one standalone sentence inserted after the §2.2 error-format bullets, all other changes are inline).

**Counts:** 22 ambiguity-pins, 6 mismatch-revisions (28 total edits; one mismatched passage in §2.1 pairs with a §3.3 clause left consistent by reference).

Changes, per section:

- §2.1 — revise — mismatch — interview-room cancellation binds to the booking's recorded `booked_by_id`, not the case's *current* active primary investigator — implementation/routes_investigations.py:390-391
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` is transport metadata read from the wall clock; all business timestamps read the logical clock — implementation/response.py:15-22
- §2.2 — insert — ambiguity — unrouted path under a resource collection yields that collection's 404 error id; unsupported method / unexpected failure yields `ERR_INVALID_REQUEST` — implementation/app.py:23-64
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST` (400) — implementation/helpers.py:158-174
- §2.4 — insert — ambiguity — clock-set answers 200 OK; missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` (400) — implementation/app.py:67-77
- §2.5 — insert — ambiguity — `version` starts at 1 on creation; all server-stamped timestamps read the logical clock — implementation/helpers.py:202-209, 221-224
- §2.7 — insert — ambiguity — missing or non-integer `expected_case_version` → `ERR_INVALID_REQUEST` (400), missing reported before existence checks — implementation/routes_cases.py:49-55
- §3.1 — insert — ambiguity — malformed/invalid-calendar `observance_date` → `ERR_INVALID_REQUEST` (400) — implementation/routes_org.py:233-238
- §3.2 — revise — ambiguity — systemic sweep window is the thirty days preceding the decision's *recording instant* (not the case's `received_at`) — implementation/cascades.py:141-150
- §3.2 — revise — mismatch — sweep triggers at a count of three **or more** (PRD said "exactly three"); impl fires at >= 3 whenever no open SYSTEMIC escalation exists for the unit+category — implementation/cascades.py:152
- §3.3 — revise — mismatch — assignment accepts the case in `CLASSIFIED` **or `ASSIGNED`** (PRD said CLASSIFIED only) — implementation/routes_cases.py:394
- §3.3 — insert — ambiguity — named investigator lacking `INVESTIGATOR` capability → `ERR_INVALID_REQUEST` (400) — implementation/routes_cases.py:411-414
- §3.3 — insert — ambiguity — every accepted assignment advances the case `version` (lifecycle moves only on the first) — implementation/routes_cases.py:476-478
- §3.3 — insert — ambiguity — `release_reason` accepted but not persisted; a release does not advance the case `version` — implementation/routes_cases.py:538, 546-550
- §3.3 — insert — ambiguity — no identity binding beyond role for opening an investigation, appending notes, submitting findings, or resuming — implementation/routes_investigations.py:53-56, 113-116, 162-165, 262-265
- §3.3 — insert — ambiguity — notes may be appended in any investigation status (no state gate) — implementation/routes_investigations.py:113-132
- §3.3 — revise — ambiguity — return-findings retains `submitted_at` and `care_concern_flag` until the next submission overwrites them — implementation/routes_investigations.py:210-213
- §3.4 — insert — ambiguity — drafting and review submission open to any `DepartmentInvestigator`, not bound to the primary investigator — implementation/routes_letters.py:48-51, 136-139
- §3.4 — revise — mismatch — non-terminal letter set for `ERR_ACTIVE_LETTER_EXISTS` includes `APPROVED` alongside DRAFT/IN_REVIEW/RETURNED (reachable-state behavior identical; text now matches the code) — implementation/routes_letters.py:30, 63-72
- §3.4 — insert — ambiguity — the approver-vs-submitter SoD gate never fires for a fast-tracked complaint (no investigation) — implementation/routes_letters.py:213-218
- §3.5 — insert — ambiguity — opening a suspension on a CLOSED/WITHDRAWN case → `ERR_CASE_INVALID_STATE`; a suspension is born with `credited_seconds` zero — implementation/routes_closure.py:122-127, 143
- §3.5 — insert — ambiguity — timeline `days_remaining` is a whole-day floor that goes negative past the due and is null while dues are unset — implementation/derived.py:156-162
- §3.6 — insert — ambiguity — manual escalation filing accepted in any case `lifecycle_status` — implementation/routes_risk.py:58-64
- §3.6 — insert — ambiguity — the substantiation-cascade auto-filed reportable event carries a null `authority_code` — implementation/cascades.py:213-224
- §3.7 — revise — mismatch — the same-case/`ADJUDICATED_SUBSTANTIATED` cross-reference check applies only to non-abuse triggers; an `escalation_id` supplied with `ALLEGED_ABUSE` is resolved (404 if missing) but exempt from the check — implementation/routes_risk.py:230-261
- §3.7 — insert — ambiguity — missing `escalation_id` on a non-abuse trigger → `ERR_INVALID_REQUEST` (400) — implementation/routes_risk.py:249-253
- §3.7 — insert — ambiguity — `authority_reference` accepted but not persisted — implementation/routes_risk.py:343
- §3.8 — insert — ambiguity — recovery issuance accepted in any case `lifecycle_status` — implementation/routes_recovery.py:45-51
- §3.8 — insert — ambiguity — `reject_reason` accepted but not persisted — implementation/routes_recovery.py:152
- §3.9 — insert — ambiguity — non-integer `score` also meets `ERR_FOLLOWUP_SCORE_INVALID` (422) — implementation/routes_closure.py:92-96
- §3.9 — insert — ambiguity — low-score reopen cascade fires only while the case still stands CLOSED — implementation/routes_closure.py:103-106
- §3.9 — insert — ambiguity — `reopen_reason` / `withdraw_reason` accepted but not persisted — implementation/routes_cases.py:218, 235
- §3.9 — revise — ambiguity — `ERR_SNAPSHOT_EXISTS` is evaluated over the cells the run would write and rejects atomically (no rows written); `force_recompute` upserts in place — implementation/routes_closure.py:256-269
- §3.9 — revise — ambiguity — `cells_created` counts every cell written including upserts; `system_rate_bp` averages the per-cell rounded headcount rates of the cells written by the run (zero when none) — implementation/routes_closure.py:270-339

Notable non-changes (verified already uniquely pinned): the §2.6 validation ladder matches impl check ordering on every route (e.g., RESTRICTED-posture before received_at-future before schema on intake; buffer before window on bookings; SoD before QRO-co-sign before open-escalation on approve); follow-up due/expires chaining (5 business days after `closed_at`, then 10 after `due_at`); exposure-weighted rate computed as a seconds ratio (equivalent to the days ratio); and the APPROVED-letter draft block being unreachable is now moot given the §3.4 set revision.
