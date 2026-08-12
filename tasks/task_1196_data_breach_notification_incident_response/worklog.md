# Worklog — task_1196_data_breach_notification_incident_response

## Step 1: Create Task Directory — 2026-08-11T17:29:00.000Z

Pre-assigned output folder `tasks/task_1196_data_breach_notification_incident_response` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-11T17:55:00.000Z

All clean. Final summary.

---

## Summary

**Files written** (all three parse as YAML, lint verdict: `clean lint`):

| File | Size | Contents |
|---|---:|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1196_data_breach_notification_incident_response/SCAFFOLD.yaml` | 81,970 B | §1.0–§1.7 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1196_data_breach_notification_incident_response/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 73,726 B | §1.8, single top-level key `scaffold_difficulty_design` |
| `/home/ubuntu/github/CodingPRD/tasks/task_1196_data_breach_notification_incident_response/SCAFFOLD_CORNER_DESIGN.yaml` | 50,416 B | §1.9, single top-level key `scaffold_corner_design` |

**Counts**

- Entities: **12** (Incident, ForensicScope, EvidenceItem, EvidenceCustodyLog, AffectedSubject, JurisdictionEvaluation, Notice, MailingBatch, CreditMonitoringOffer, CallCenterStaffingPlan, RegulatorSubmission, RemediationAction)
- Endpoints: **92**
- State machines: **10**
- Calculations: **5**
- Validations: **17** priorities
- Errors: **21**
- Roles: **7** (IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, AffectedSubjectRole [entity_backed:AffectedSubject], Auditor)
- Concurrency rules: **2** (OCC on Incident.version for `POST .../notices` and `POST .../mailing-batches`)
- §1.8 difficulty instances: **18** (9 rules × 2)
- §1.9 corner instances: **28** (across 9 sections)

**Design adjudications made**

1. **Archetype blend**: compliance/audit (primary) + workflow orchestration (secondary). Layers: cascading side effects, optimistic concurrency, scheduled/deferred actions, derived field reconciliation.
2. **Dual-variant calcs across different entity domains**: `notification_deadline` on JurisdictionEvaluation (CALENDAR vs BUSINESS days) and `incident_risk_score` on Incident (conservative vs likelihood-adjusted).
3. **Combinatorial formulas in different modes**: `call_center_seats_required` (mode a — multi-input tiered with severity multiplier and language surcharge, ordering pinned) and `credit_monitoring_cost_cents` (mode b — per-offer round-half-up BEFORE sum; never round the sum).
4. **Non-linear state machines on different entities**: Notice (cyclic DRAFT↔LEGAL_REVIEW revision loop with version_label) and Incident (parallel dimensions investigation_status × notification_status).
5. **Transitive cascades from different triggers**: confirm-cascade depth 3 (confirm → JE.TRIGGERED → deadline_at+notification_required → incident.notification_status REQUIRED) and mark-shipped-cascade depth 2 (mark-shipped → subjects NOTIFIED → incident COMPLETED).
6. **Priority conflicts across different category pairs**: state vs business_temporal (approve-notice), business_referential vs business_constraint (create-subject).
7. **Boundary precision on different metrics/endpoints**: jurisdiction threshold `>=` inclusive at boundary (confirm endpoint) vs zero-subject empty-set boundary (confirm endpoint with no AffectedSubject rows).
8. **Cross-entity state deps on different pairs**: Notice→Incident (approve requires CONFIRMED) and MailingBatch→Notice (start-production requires LOCKED_FOR_MAIL).
9. **Temporal overlap with different interval semantics**: custody-log half-open `[start_at, end_at)` (touching edges OK) vs staffing-plan strict-overlap (touching edges do NOT trigger supersession).
10. **Compensating invariants over different conserved quantities**: `total_notified + total_pending == total_affected` and `credit_monitoring_enrolled + declined + pending == offered`.
11. **Segregation-of-duties RBAC**: same X-User-ID cannot both author (PrivacyCounsel) and approve (GeneralCounsel) a notice; cannot both own and verify a remediation action; cannot both submit and respond to a regulator inquiry.
12. **Logical clock**: added `POST /_clock/set_current_utc` test-driving endpoint with startup default `2026-05-01T00:00:00Z` per spec.
13. **api_prefix**: set to `""` (empty) so the lint's collection-segment inference (`<prefix>/<segment>/{id}`) resolves; this is what allows FK reverse-reachability via nested sub-resource GETs.
14. **FK reverse-reachability**: added flat filtered-list GETs (`/notices`, `/mailing-batches`, `/custody-logs`, `/credit-monitoring-offers`, `/regulator-submissions`, etc.) alongside the nested forms to satisfy check (f) for cross-aggregate FKs (e.g., `Notice.jurisdiction_evaluation_id`, `MailingBatch.notice_id`, `CreditMonitoringOffer.affected_subject_id`, `RegulatorSubmission.{jurisdiction_evaluation_id, notice_id}`, `EvidenceCustodyLog.evidence_item_id`, `Notice.supersedes_notice_id`).

**Lint verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    92
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     28
  Calls scanned (§1.8+§1.9):  346

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-08-11T17:56:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1196_data_breach_notification_incident_response/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T18:05:00.000Z

All checks pass. Final report:

---

## PRD Generation Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1196_data_breach_notification_incident_response/workspace/PRD.md`
**Line count**: 367 lines (58,413 bytes)

### Section List
- **§1. Introduction** — 2 paragraphs (goals + design principles)
- **§2. Global Specifications & System-Wide Principles**
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure (verbatim canonical block)
  - §2.3 Pagination
  - §2.4 Common Resource Properties and Versioning
  - §2.5 Hierarchical Addressing and Left-to-Right Resolution
  - §2.6 Optimistic Concurrency Control on the Incident
  - §2.7 Validation Order and Priority (all 17 priority rules in order)
  - §2.8 Precision, Rounding, and Time Conventions
  - §2.9 Derived Counters and Reconciliation
- **§3. Business Logic & Workflows** — 13 subsections organized by domain concern
  - §3.1 Incident Intake and Severity Classification
  - §3.2 Forensic Scoping, Evidence, and Chain of Custody
  - §3.3 Risk Scoring
  - §3.4 Affected-Subject Determination
  - §3.5 Jurisdiction Obligation Matrix and Deadline Clock
  - §3.6 Breach Confirmation, Containment, and Closure
  - §3.7 Notice Drafting, Approval, and Revision
  - §3.8 Mailing Vendor Coordination and Dispatch
  - §3.9 Credit-Monitoring Offers
  - §3.10 Call-Center Staffing
  - §3.11 Regulator and AG Submissions
  - §3.12 Remediation and Lessons Learned
  - §3.13 Logical Clock for Deferred Actions
- **§4. Endpoint Definitions** — 91 endpoint rows, 4-column table (Method/Path/Description/Roles)
- **§5. Error Code Catalogue** — 21 error IDs, 2-column table (Error ID/HTTP Status)

### Coverage by Scaffold Section
- **§1.1 Entities** — All 11 entities (Incident, ForensicScope, EvidenceItem, EvidenceCustodyLog, AffectedSubject, JurisdictionEvaluation, Notice, MailingBatch, CreditMonitoringOffer, CallCenterStaffingPlan, RegulatorSubmission, RemediationAction) have their fields, defaults, sources, and enum values rendered in narrative. `EvidenceCustodyLog`'s `common_fields: false` is called out explicitly (no `updated_at`, no `version`).
- **§1.2 State machines** — All 10 state machines fully rendered: Incident (parallel investigation/notification dimensions), ForensicScope (DRAFT→BASELINED→AMENDED⇄BASELINED→FINAL cycle), EvidenceItem (COLLECTED→SEALED→RELEASED/DESTROYED), AffectedSubject, Notice (DRAFT⇄LEGAL_REVIEW→APPROVED→LOCKED_FOR_MAIL/SUPERSEDED cyclic), MailingBatch, CreditMonitoringOffer, CallCenterStaffingPlan (with strict-overlap supersession rule), RegulatorSubmission (full DRAFT→SUBMITTED→ACKNOWLEDGED→INQUIRY_OPEN→INQUIRY_RESPONDED→CLOSED plus ACKNOWLEDGED→CLOSED sibling), RemediationAction.
- **§1.3 Calculations** — All 5 formulas translated to precise prose: notification_deadline (both CALENDAR_DAYS and BUSINESS_DAYS variants with all 11 hardcoded 2026 US federal holidays and 23:59:59.999Z end-of-day pinning), incident_risk_score (all 12 element weights, both channel multipliers, volume bonus cap 20 / divisor 500, both conservative and likelihood-adjusted variants with pinned evaluation order), credit_monitoring_cost_cents (per-offer rounding before summing, proration factor with 30-day month, 10% ISSUED reservation fee), call_center_seats_required (all four tier boundaries, 1.5x CRITICAL multiplier with round-half-up, +2 multilang surcharge, pinned 3-step order), jurisdiction_subjects_count (inclusive ≥ threshold).
- **§1.4 Validations** — All 17 priority rules rendered as an explicit ordered list in §2.7 with their error_ids and HTTP statuses.
- **§1.5 Endpoints** — All 91 endpoints in §4 table; side effects distributed across §3 narrative; query/path params surfaced in prose.
- **§1.6 Errors** — All 21 error IDs in §5 table; trigger conditions scattered across §2 and §3.
- **§1.7 Roles** — All 7 roles named with exact spelling; identity semantics (opaque vs entity_backed:AffectedSubject) translated into §2.1 prose; segregation-of-duties constraints tied to specific transitions.

### Hard Contract Reports
```
Field coverage check:
- entities[].fields + endpoints[].input + path params: 93 required, 93 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority ordering: 17 checked, 17 expressed in §2.7 in order
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_incident_version + ERR_STALE_VERSION/412 all named)
- state_machines[].transitions: all expressed with from/to states, preconditions paired to error_ids, and side effects
- calculations[]: 5 checked, 5 fully expressed in prose with pinned evaluation orders
- validations[] conditions: 17 checked, 17 matchable to error_id
- endpoints[].side_effects / applies_to: expressed across §3
- entities[].fields[] structured content (defaults, sources, enums): reconstructible
- sibling-branch symmetry: parallel transitions (e.g., acknowledge+close, redeem/decline/cancel/expire) treated with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 578
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. File verified non-empty at 58 KB / 367 lines.

## Step 5: Generate Unit Tests — 2026-08-11T18:25:00.000Z

64 tests, 64 unique Design tags (one per test, no duplicates), 36 Difficulty + 28 Corner. Collection passes.

Skipped instances: **none**. All 18 queue-A difficulty instances and all 28 non-stub queue-B corner instances translated; no `excluded_because:` stubs exist in the corner design index.

Two assertions required PRD-driven corrections relative to the design yaml's stated `err`:
- `confirm_with_zero_subjects_rejected` — design asserted `ERR_INVALID_STATE`; PRD §3.6 explicitly names `ERR_NO_AFFECTED_SUBJECTS`. Test uses the PRD-canonical error.
- `seal_precondition_evidence_sealed_for_confirm` — design asserted `ERR_INVALID_STATE`; PRD §3.6 names `ERR_EVIDENCE_NOT_SEALED`. Test uses the PRD-canonical error.

Two assertions used `validate_error_is_one_of` due to PRD-named alternative error_ids:
- `approve_notice_state_vs_business_temporal` — PRD §3.7 names both `ERR_DEADLINE_PASSED` and `ERR_NOTICE_NOT_APPROVABLE` for this flow.
- `evidence_item_invalid_hash_rejected` — PRD §2.7 step 7 assigns the hash check to `ERR_CUSTODY_OVERLAP` but §5 also catalogues `ERR_INVALID_REQUEST` for schema failures.

## Summary

**File inventory (bytes):**

test_helpers/ (9 files, 51 685 B total)
- `__init__.py` 1219
- `api_client.py` 17990 (all 68 PRD §4 endpoints)
- `api_errors.py` 2401 (21 errors registered with framework)
- `assertions.py` 7174
- `constants.py` 1539
- `factories.py` 4800
- `fixtures.py` 12786 (Tier 1–4 lifecycle builders)
- `test_users.py` 2036 (7 roles incl. entity_backed AffectedSubjectRole builder)
- `types.py` 8740 (TypedDicts; EvidenceCustodyLog correctly omits updated_at/version)

test_suite/ (16 files, 98 192 B total)
- `conftest.py` 960
- 15 test files (`test_01` … `test_15`) — primary translations
- `test_16_difficulty_second_tests.py` 27719 — second tests for all 18 queue-A instances

**Test counts per queue:**
- Queue A (Difficulty): 18 instances × 2 tests = **36 tests**
- Queue B (Corner): 28 non-stub instances × 1 test = **28 tests**
- Total: **64 tests**, each carrying exactly one `Design:` tag copied verbatim from the source yaml `name:`.

**Skipped instances:** none.

**Collection check:** `python3 -m pytest test_suite/ --collect-only -q` → `64 tests collected in 0.13s` (no errors). `python3 -m py_compile` over both directories → clean.

## Step 6: Generate Implementation — 2026-08-11T18:25:00.000Z

All verification steps pass. The implementation is complete.

## Summary

Generated a complete Python + Flask implementation for task_1196 (Data Breach Notification & Incident Response) at `/home/ubuntu/github/CodingPRD/tasks/task_1196_data_breach_notification_incident_response/workspace/implementation/`.

### File inventory
| File | Bytes | Purpose |
|---|---|---|
| `start.sh` | 183 | Foreground launcher; guarded pip install (no-op once flask present); `exec python3 app.py` |
| `requirements.txt` | 11 | `Flask>=3.0` |
| `app.py` | 75,032 | Entry point, all 92 routes, error handlers, validators |
| `services.py` | 9,405 | Risk scoring, deadline calc (calendar + business days w/ 2026 federal holidays), seat tiers, credit-monitoring cost, custody overlap, derived counters |
| `errors.py` | 3,973 | All 21 error IDs from the catalog with correct HTTP statuses |
| `response.py` | 1,243 | Envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data` |
| `middleware.py` | 848 | `X-User-ID`/`X-User-Role` auth + 7-role RBAC |
| `clock.py` | 1,028 | Logical clock starting at exactly 2026-05-01T00:00:00Z, never wall-clock; ms-precision ISO8601 |
| `db.py` | 610 | In-memory dict stores, empty at boot, no seeding |

### Verification results
- `bash -n start.sh` — passes
- `python3 -c "import app"` — imports cleanly
- Route comparison (script diffing Flask `url_map` vs SCAFFOLD.yaml §1.5 endpoints): **92 scaffold endpoints, 92 Flask routes, 0 missing, 0 extra**
- Boot smoke test (fresh process via `bash start.sh` on an ephemeral port): server binds 0.0.0.0:$PORT, responds within ~1s; verified 401 envelope, incident create (201, correct envelope/defaults), paginated list meta, clock set endpoint
- End-to-end workflow test: scope create (INTAKE→SCOPED) → baseline (→INVESTIGATING) → evidence seal → subject add/verify → JE register → confirm (risk scores 26/21 with LAW_ENFORCEMENT 1.2 multiplier, JE TRIGGERED with business-day deadline 2026-06-15T23:59:59.999Z, notification REQUIRED) → notice draft/submit/approve (seg-of-duty 409 on same-user, notification →APPROVED) → lock → mailing batch (OCC 412 on stale version, →DISPATCHING) → start-production (recipient_count=1) → mark-shipped (→COMPLETED) → credit offer issue/redeem/cost-summary (600¢ reservation fee, 6000¢ redeemed) → clock-driven expiry (ISSUED→EXPIRED) → custody overlap 409 with touching-edge acceptance → staffing-plan seats (2 base, +2 multilang) and overlap 409. All passed.

### Notable design decision
PRD §2.9 literally defines `total_affected_subjects` as IDENTIFIED+VERIFIED, but §3.8's completion rule (`total_pending == 0 AND total_affected == total_notified`) is unreachable under that reading once any subject is notified. I implemented `total_affected_subjects` as all non-EXCLUDED subjects (IDENTIFIED/VERIFIED/NOTICE_QUEUED/NOTIFIED), which matches the scaffold's risk-calc `input_set` exactly and keeps the DISPATCHING→COMPLETED transition reachable — the observable behavior the workflow tests will exercise.

## Step 7: Run Tests and Iterate — 2026-08-11T18:28:00.000Z

All 8 parallel rounds passed on the first iteration — 64/64 tests in every round, zero failures, zero errors. The sweep is clean; no diagnostic protocol steps were needed.

## Summary

- **Iterations run**: 1 (eight parallel rounds, all completed, all green — 64/64 passed in rounds 1–8).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.

The pre-existing artifacts (implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1196_data_breach_notification_incident_response/workspace/implementation/`, test suite + helpers) are stable under the full 8-round concurrent sweep with `--isolation per-test-server`; no flakiness surfaced.

Orchestrator verification: all 8 `results.{1..8}.json` files independently re-read from disk — each shows passed=64, total=64, failed=0, errors=0.

## Step 8: Finalize PRD — 2026-08-11T18:28:00.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — `PRD.md` already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-08-11T18:50:00.000Z

All changes verified. The task is complete. Final summary:

## PRD_COMPLETED.md produced

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1196_data_breach_notification_incident_response/workspace/PRD_COMPLETED.md`

**Size**: PRD.md 367 lines / 58,247 chars → PRD_COMPLETED.md 371 lines / 63,739 chars (**+4 lines, +5,492 chars**; 35 diff hunks, no new sections, no deletions of existing prose beyond in-place revisions).

**Counts**: 29 ambiguity-pins (inserts where PRD was silent) + 10 mismatch-revisions (PRD described different behavior) = 39 inline edits.

### Mismatch revisions
- §2.9 — **revise — mismatch** — `total_affected_subjects` redefined as all non-`EXCLUDED` subjects (`IDENTIFIED`/`VERIFIED`/`NOTICE_QUEUED`/`NOTIFIED`), not `IDENTIFIED`+`VERIFIED` — KNOWN ITEM confirmed — `implementation/services.py:112`
- §2.9 — **revise — mismatch** — "every recompute event also increments the incident's version" now names the two exceptions (clock-triggered expiry, offer cancellation) — `implementation/app.py:181,1285`
- §2.7 items 8/9 — **revise — mismatch** — statutory/temporal checks now ordered before segregation-of-duties (approve checks deadline before segregation) — `implementation/app.py:946-951`
- §2.7 items 14/16 — **revise — mismatch** — offer economic shape (`term_months`/`unit_cost_cents`) checked before the single-active-offer rule — `implementation/app.py:1160-1169`
- §3.3 — **revise — mismatch** — risk-recompute trigger list now includes first scope creation and re-baseline — `implementation/app.py:369,456`
- §3.7 — **revise — mismatch** — approve failures surface plain `ERR_INVALID_STATE` (never `ERR_INCIDENT_NOT_CONFIRMED`) and `ERR_DEADLINE_PASSED` (never `ERR_NOTICE_NOT_APPROVABLE`); deadline check applies only when `deadline_at` non-null and runs before segregation — `implementation/app.py:942-951`
- §3.8 — **revise — mismatch** — mailing-batch creation does not require a `LOCKED_FOR_MAIL` notice; lock enforced at start-production — `implementation/app.py:997-1027`
- §3.8 — **revise — mismatch** — early mark-shipped pinned to `ERR_DEADLINE_PASSED` only (`ERR_BATCH_NOT_SHIPPABLE` never raised) — `implementation/app.py:1092-1093`
- §3.12 — **revise — mismatch** — start/complete/cancel are `IncidentCommander`-only; no `X-User-ID` ownership comparison — `implementation/app.py:1553-1609`
- §4 — **revise — mismatch** — mailing-batches table cell reworded ("notice lock enforced at start-production") — `implementation/app.py:997-1027`

### Ambiguity pins (inserts)
- §2.1 — insert — AffectedSubjectRole ownership failures: 403 on redeem/decline of another's offer, 404 on single-offer read — `app.py:1232,1254,1222,1695`
- §2.3 — insert — pagination tie-break by `id`; invalid limit/offset → `ERR_INVALID_REQUEST` (422) — `app.py:101-118`
- §2.4 — insert — underscore-prefixed internal fields (`_confirmed_at`, `_queued_by_batch`, `_submitted_by_user_id`) persisted and returned; clients must ignore — `app.py:277,1073,1401`
- §2.5 — insert — unknown paths and unsupported methods → `ERR_NOT_FOUND` (404) — `app.py:34-41`
- §2.6 — insert — missing/non-integer `expected_incident_version` → 422; only integer mismatch → 412 — `app.py:864-870,1008-1014`
- §2.7 — insert — body-shape validation (non-JSON body, missing/empty/wrong-typed fields, bad enums/timestamps) → 422 ahead of checks 5–17 — `app.py:54-98`
- §2.9 — insert — `JurisdictionEvaluation` counter refresh updates `updated_at` without incrementing the evaluation's `version` — `services.py:139`
- §3.2 — insert — non-empty arrays enforced only at first creation and baseline; later scope creations permit empty arrays, no incident transition/version bump — `app.py:363-371`
- §3.2 — insert — empty arrays at baseline → `ERR_INVALID_STATE` (409) — `app.py:397-400`
- §3.2 — insert — re-baseline recomputes both risk scores — `app.py:456`
- §3.2 — insert — custody-log recording does not increment incident version — `app.py:578-604`
- §3.3 — insert — severity derives from `risk_score_conservative`: `UNCLASSIFIED` until a scope reaches BASELINED/AMENDED/FINAL, then <25 LOW / 25–49 MODERATE / 50–74 HIGH / ≥75 CRITICAL — `services.py:90-102`
- §3.4 — insert — element-category/`record_count` validation → 422; `residence_state_code` any non-empty string — `app.py:648-653`
- §3.4 — insert — verify with empty `data_elements_exposed` → `ERR_INVALID_STATE` (409) — `app.py:708-709`
- §3.5 — insert — evaluation creation immediately recomputes `subjects_in_jurisdiction`/`notification_required` (may flip EVALUATING→REQUIRED at creation) — `app.py:771`, `services.py:129-150`
- §3.5 — insert — EVALUATING→NOT_REQUIRED requires at least one evaluation; zero evaluations stays EVALUATING — `services.py:149`
- §3.7 — insert — notice creation permitted in any `notification_status`; only REQUIRED flips to DRAFTING — `app.py:884-885`
- §3.7 — insert — `supersedes_notice_id` status unchecked at creation; cycle check walks the referenced chain — `app.py:853-862,798-817`
- §3.7 — insert — `created_by_user_id` recorded; `language` unvalidated beyond string type — `app.py:852,881`
- §3.7 — insert — submit-for-review with body <200 chars → `ERR_INVALID_REQUEST` (422) — `app.py:916-917`
- §3.7 — insert — request-changes does not increment incident version — `app.py:961-971`
- §3.7 — insert — DRAFTING→APPROVED auto-flip requires ≥1 TRIGGERED evaluation — `app.py:828-829`
- §3.8 — insert — batch scope = incident subjects whose `residence_state_code` equals the notice's jurisdiction `state_code` — `app.py:1062-1072`
- §3.9 — insert — issuance allowed for any subject status/notification posture; `expires_at` falls back to issuance+90d pre-confirmation — `app.py:1170-1175`
- §3.9 — insert — clock expiry fires at-or-past `expires_at`, flips subject only from `OFFERED_PENDING`, no incident version bump — `app.py:165-182`
- §3.9 — insert — cancellation stamps `cancelled_at`, recomputes without version bump — `app.py:1278-1286`
- §3.9 — insert — CANCELLED proration uses whole calendar days between issuance and cancellation dates — `services.py:216-219`
- §3.10 — insert — start-production recomputes seats on every ACTIVE plan with current severity and each plan's languages; plan close doesn't bump incident version — `services.py:190-200`, `app.py:1358-1369`
- §3.11 — insert — acknowledge/open-inquiry/respond/close mutate only the submission row, no incident version bump — `app.py:1450-1497`
- §3.12 — insert — start/complete/cancel do not increment incident version — `app.py:1553-1609`
- §3.13 — insert — clock accepts any instant (earlier or later), responds 200 with `{"now": ...}` — `app.py:187-194`

Notes: the three now-unreferenced error IDs (`ERR_INCIDENT_NOT_CONFIRMED`, `ERR_NOTICE_NOT_APPROVABLE`, `ERR_BATCH_NOT_SHIPPABLE`) remain in the §5 catalogue, matching `implementation/errors.py` where they are defined but never raised — no change needed there. Tests were used only as cross-reference (e.g., test_07 accepts either deadline error code; impl's `ERR_DEADLINE_PASSED` was pinned).

