# Worklog — task_0085_i9_everify_onboarding

Scenario: Onboarding I-9 & E-Verify: identity document review (List A/B/C), 3-day deadline, Reverification, E-Verify TNC handling, Section 3 update, F-1 OPT STEM extension

## Step 1: Create task directory — pre-assigned (auto-index scan skipped)

Task directory `tasks/task_0085_i9_everify_onboarding/` pre-created and reserved with `workspace/` subdirectory. Auto-index scan of ./tasks/ skipped per orchestration directive to avoid parallel ID collision.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-01T18:59:00.000Z

All three required files are present with correct single top-level keys, and the lint verdict is clean. The scaffold is complete.

Generated a clean, lint-passing Expert-difficulty scaffold for **task_0085_i9_everify_onboarding** (Onboarding I-9 & E-Verify). Final `scaffold_lint.py` verdict: **clean lint** — 259 §1.8/§1.9 calls conform to §1.5, all 9 FKs have reverse-reachability.

**Complexity profile:** compliance/audit primary × workflow-orchestration secondary; flat topology; branching state-machine shape; segregation-of-duties role model; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Entities (7):** Onboarding, I9Form, IdentityDocument, EVerifyCase, WorkAuthorization, ReverificationEvent (Section 3), AuditEntry (append-only, common_fields:false). 9 FKs including a self-referential `WorkAuthorization.supersedes_id`.

**State machines (3):** Onboarding (8 states, branching — CREATED→…→AUTHORIZED/TERMINATED_NONCONFIRMED/EXPIRED_UNAUTHORIZED with reverification cycle); EVerifyCase (branching fork-join — SUBMITTED→{AUTHORIZED, TNC_ISSUED→{REFERRED, FINAL_NONCONFIRMATION}}); WorkAuthorization (cyclic ACTIVE→EXTENDED→SUPERSEDED via STEM + Section 3). Plus 2 OCC concurrency rules on Onboarding.version (section2-complete and everify-case create), both 412.

**Calculations (6):** section2_deadline (3 business days, weekends + 10 federal holidays), everify_deadline + was_late, section2_document_sufficiency (List A vs List B+C exactly-one-path), document_validity (strict-`>` expiry, receipt exemption), stem_extension_window (inclusive-`<=` filing window, 180-day cap-gap clamp), onboarding_compliance_risk (weighted, sum-then-round-then-clamp). Dual-variant on STEM cap-gap and on risk clamp — distinct entity domains.

**Validations:** 15 priority-ordered rows (auth → segregation-of-duties → existence → state → business safety/constraint/temporal/referential → OCC → request). **Errors:** 16-code catalog. **Roles (3):** HRReviewer, EVerifyOperator, ComplianceOfficer (all opaque), with enforced segregation of duties on override. **Endpoints:** 29 (incl. `/_clock/set_current_utc` test-driving endpoint and an `advance-lifecycle` system-trigger endpoint).

**Difficulty design (§1.8):** all 9 rules × 2 = **18 instances**, each with falsifiable distinguishing_aspect, executable setup_api_calls chains, and pre-computed literal asserts (deadlines, cap-gap dates, risk scores verified by code).

**Corner design (§1.9):** **33 active instances + 3 excluded_because stubs** spanning all 9 claim-extraction sections (entities 8, state_machines 7, calculations 3, validations 4, endpoints 2, errors 4, rbac 4, cross_cutting 3, consistency 1). No duplicate names across both files; all stub `difficulty_instance` references resolve.

**Notable design choices / fixes made:** set `api_prefix: ""` (flat multi-collection topology) so FK reverse-reachability resolves; redefined `Onboarding.is_overdue` as a latching compliance flag (was momentary, which broke the risk-65 assert); removed 4 dead enum values (I9Form.VOID, IdentityDocument.REJECTED, EVerifyCase.CLOSED, ReverificationEvent.VOIDED) for enum closure and reworded the duplicate-case guard to "non-terminal"; added explicit clock-sets before STEM filings; added `/reverification-events` and `/audit-entries/{id}` GETs for FK reverse-reachability. No forbidden concurrency vocabulary; no `id` used in business decisions.

## Step 3: Copy shared files — 2026-06-01T19:00:00.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-01T19:10:00.000Z

PRD generated at `workspace/PRD.md` — ~5,470 words / ~39.9 KB / 242 lines.

**Sections covered:**
- §1 Introduction (2 paragraphs, compliance-narrative angle)
- §2 Global Specs (9 subsections): RBAC + opaque-identity + segregation-of-duties; §2.2 verbatim envelope; pagination; common resource properties (with `AuditEntry` as the `common_fields:false` exception); flat-topology nested-path/reverse-reachability resolution; precision + deterministic clock + business-day arithmetic; OCC on the two onboarding writes; validation priority ordering; state-propagation + audit trail
- §3 Business Logic (8 subsections, organized by lifecycle stage): onboarding creation + Section 1; the 3-business-day deadline + latching `is_overdue`; document presentation + Section 2 sufficiency; E-Verify submission + adjudication + TNC/referral; finalization + compliance override; work authorizations + STEM cap-gap + Section 3 reverification; clock-driving + advance-lifecycle; compliance-risk score
- §4 endpoint table (29 rows, 4 columns); §5 error table (16 rows, 2 columns)

**Hard Contract reports:** Field coverage PASS (58/58 required fields present); Rule coverage PASS (15/15 validations, 2/2 OCC, 3 state machines fully expressed, 6/6 calculations, sibling-branch symmetry OK); Path purity PASS (330 backtick tokens scanned, 0 path/method tokens in §3).

**Notable scattering/coverage decisions:** `section2-complete` params split across §3.3 (document_ids + sufficiency/expiry) and §2.7 (expected_onboarding_version OCC) + §3.2 (deadline/overdue); `everify_deadline = section2_deadline` stated not re-derived; `was_late` strict-`>` co-located with submission; §2.2 emitted byte-for-byte from the canonical envelope; `status` query-param added to §2.5 reverse-reachability prose; removed accidental closing-tag capture so doc ends cleanly at §5.

## Step 5: Generate unit tests — 2026-06-01T19:30:00.000Z

**Test infrastructure generated for task_0085_i9_everify_onboarding (Expert).**

**test_helpers/ (9 modules):** `__init__.py` (barrel export), `types.py` (7 entity TypedDicts + 10 status/role enums; `AuditEntry` correctly omits `version`/`updated_at` as `common_fields:false`), `api_client.py` (ApiClient with 30 endpoint methods), `api_errors.py` (16-error `ApiErrorId` enum + HTTP-status map registered with framework), `assertions.py` (per-entity assertions + append-only/risk-summary checkers), `factories.py` (input-only payload factories), `constants.py` (deadline/cap-gap/risk-weight thresholds), `test_users.py` (3 opaque roles — shared constants + `make_*_headers(user_id)` builders for segregation-of-duties threading), `fixtures.py` (5-tier composite setup: Section 1/2 progression, E-Verify lifecycle, STEM base, reverification-due, clock control).

**test_suite/ (6 files + conftest, 69 test functions):**
- test_01 onboarding lifecycle/calculations (18), test_02 document review/Section 2 (13), test_03 E-Verify adjudication (11), test_04 work-auth/STEM/reverification (8), test_05 validation-priority/state (11), test_06 concurrency/access-control (8).

**Coverage (design-index-only, both queues fully satisfied):**
- **Queue A (Difficulty):** all 18 instances × ≥2 tests = 36 tagged tests. 0 shortfalls, 0 skips.
- **Queue B (Corner):** all 33 non-stub instances × ≥1 test = 33 tagged tests. 0 shortfalls. The 3 `excluded_because:` stubs (`stem_window_missed_triggerable`, `referral_window_closed_triggerable`, `document_expired_triggerable`) were NOT translated; all 3 cross-references resolve to valid Queue A `resource_temporal_overlap`/`boundary_precision_check` instances that own those assertions.

**Instances skipped under the PRD-first filter:** none — every non-stub instance survived both the verbatim-coverage and unique-derivability conditions, with PRD prose backing each asserted `error_id`, threshold (deadline 06-04/06-23, cap-gap 120/180→2027-01-28/2027-03-29, receipt +90d→2026-08-31, risk 0/65/100, strict-`>` expiry, inclusive `<=` STEM window), transition, and side effect.

**Verification:** all 69 tests collect under pytest; all 102 PRD citations confirmed verbatim substrings of PRD.md; every test carries exactly one `Design:` tag resolving to a real instance; no scaffold/Table references leaked.

## Step 6: Generate implementation — 2026-06-01T19:30:00.000Z

**Stack:** Python 3 + Flask 3.0.3, in-memory dict store (wiped every boot, zero seeding). Boots in ~2s, binds `0.0.0.0:$PORT` (default 10000), foreground via `exec`.

**Files emitted (23, all in `workspace/implementation/`):** `start.sh` (guarded `pip install` on missing flask, `exec python3 app.py`), `requirements.txt`, `app.py` (blueprint registration + error handlers: ApiError→envelope, 404/405→ERR_NOT_FOUND, catch-all). Foundation: `errors.py` (16-entry catalog), `clock.py` (deterministic logical clock + business-day/holiday arithmetic), `response.py` (meta/response_type/data envelope), `db.py` (UUID/created_at/updated_at/version), `middleware.py` (auth+RBAC+pagination), `validation.py`, `serializers.py`, `listing.py`. `routes/` (7 modules) + `services/` (audit, calculations, lifecycle).

**Endpoints (28)** — all from the table: onboardings (+section1-attest, section2-complete, finalize, override, advance-lifecycle, risk), identity-documents, i9-forms (+section3 GET/POST), reverification-events, everify-cases (+result, refer), work-authorizations, audit-entries, `_clock/set_current_utc`.

**State machines encoded:**
- Onboarding: CREATED→SECTION1_COMPLETE→SECTION2_COMPLETE→{EVERIFY_PENDING→AUTHORIZED/TERMINATED_NONCONFIRMED | finalize→AUTHORIZED}; AUTHORIZED→REVERIFICATION_DUE→{AUTHORIZED via section3 | EXPIRED_UNAUTHORIZED}. The two clock transitions are separate advance-lifecycle events (single call applies at most one), making the reverification path reachable — bug caught and fixed.
- EVerifyCase: SUBMITTED→{EMPLOYMENT_AUTHORIZED | TNC_ISSUED→{REFERRED→{AUTH|FINAL} | FINAL via NO_ACTION/lapse}}, with onboarding cascades + audit actions per PRD §3.4.
- WorkAuthorization: ACTIVE→{EXTENDED (STEM) | SUPERSEDED (section3) | EXPIRED (clock)}.

**Calculations:** section2_deadline / everify_deadline (3 business days, weekend+2026-federal-holiday skip, 23:59:59.999Z stamp), document_validity (strict `>` clock, receipts exempt, null=non-expiring), section2_document_sufficiency (exact List A XOR List B+C), STEM cap-gap (min(requested,180), inclusive `<=` filing window), receipt 90-day deadline, referral_deadline (+10 gov business days), compliance_risk (Decimal sum-then-round-half-up, clamp [0,100]).

**Validations:** full 15-priority ordering enforced; OCC field `expected_onboarding_version` on section2-complete and everify-case create; `is_overdue` latches and recomputes on read without bumping version.

**Verification:** smoke-tested end-to-end across happy path, TNC+referral, referral-window-closed+lapse, STEM cap-gap clamp, finalize, two-step reverification, EXPIRED_UNAUTHORIZED, overdue latching+override, SoD, duplicate-case guard, late-reason, all error codes, pagination, priority ordering, fresh-boot empty state. All 22 modules compile clean.

## Step 7: Run tests and iterate to PASS — 2026-06-01T19:45:00.000Z

All tests pass cleanly. Final result: all 8 parallel rounds green, 69/69 tests each, zero flakiness.

**Iterations run:** 2 sweeps (1 diagnostic baseline + 1 confirmation).

**Baseline failures (stable across all 8 rounds — no flakiness):**
1. `test_active_authorization_count_stays_one_across_reverification`
2. `test_superseded_authorization_count_grows_by_exactly_one_on_reverification`
3. `test_workauth_cycle_extended_then_superseded_by_section3`
4. `test_risk_score_sum_then_round_then_clamp_to_100`

**Tests deleted:** none. Every failing test was PRD-covered and uniquely derivable.

**Fixes applied to implementation/** (the 3 workauth failures were one root-cause bug):
- `workspace/implementation/routes/i9_forms.py` — `record_section3()`: when recording a Section 3 reverification, the code resolved "the prior WorkAuthorization" (PRD §3.6: "the prior `WorkAuthorization` is marked `SUPERSEDED`") via `controlling_work_auth()` *after* the new authorization already existed. Since the new auth has the latest `effective_valid_until`, it was wrongly selected as "prior," and the `prior["id"] != new_auth["id"]` guard then skipped the supersede entirely — leaving the genuinely-prior auth stuck at `EXPIRED` (from the earlier clock-driven advance) instead of `SUPERSEDED`. Fixed by passing `exclude_id=new_auth["id"]` so the actual prior controlling record is found and superseded.
- `workspace/implementation/services/lifecycle.py` — `controlling_work_auth()`: added an `exclude_id` parameter to omit the just-presented authorization from the controlling-record selection.

**Fixes applied to test_helpers/ / test_suite/:**
- `test_suite/test_01_onboarding_lifecycle_calculations.py` — `test_risk_score_sum_then_round_then_clamp_to_100` (STEP 2, test-vs-PRD consistency): the test claimed a "maxed posture should clamp to 100" but its setup completed Section 2 *on time* (clock 06-02 ≤ deadline 06-04), so `is_overdue` never latched and the faithful PRD sum was only 60 — never exceeding the clamp. Made the setup faithful to the rule under test: advanced the clock to 06-10 before completing Section 2 (latching `is_overdue` = +40) and accepted two receipts via the List B + List C path (+15 each), yielding a genuine 40+25+20+30 = 115 that actually exercises the clamp to 100. PRD §3.8 verbatim-covers each weight and "clamped so that the final `risk_score` never exceeds 100."

**Verification:** Full 8-round parallel sweep under `--isolation per-test-server` — every round 69/69, union of failures empty.

## Step 8: Finalize PRD — 2026-06-01T19:55:00.000Z

**PRD.md vs PRD_FINALIZED.md:** 242 lines → 242 lines (0.0% line delta; edit is inline on the §3.6 Reverification line). Words: 5470 → 5539 (+69 words, +1.26%).

**Changes (one bullet):**
- **§3.6 (Reverification / Section 3)** — *insert* — pinned how "the prior `WorkAuthorization`" is identified and that it is superseded even from an already-`EXPIRED` state. Added a sentence defining the prior as "the controlling authorization being replaced — the non-`SUPERSEDED` record on this onboarding with the latest `effective_valid_until`, considered to the exclusion of the just-presented `work_authorization_id`" and noting it is marked `SUPERSEDED` "whether it is currently `ACTIVE`, `EXTENDED`, or already `EXPIRED`." — `routes/i9_forms.py:110-114`, `services/lifecycle.py:49-64`.

**Per-edit pre-edit search log:**
- **Edit 1 — §3.6 prior-WorkAuthorization supersede.** (a) Subject: selection of "the prior `WorkAuthorization`" superseded on Section 3, and the status it is superseded from. (b) Impl paths enumerated: `routes/i9_forms.py:104-120` (Step 7 site, `exclude_id=new_auth["id"]`, three-status guard ACTIVE/EXTENDED/EXPIRED); `services/lifecycle.py:49-64` (`controlling_work_auth` selection: non-SUPERSEDED, non-null effective_valid_until, id != exclude_id, max by effective_valid_until); `services/lifecycle.py:113-127,132-146` (advance paths flip controlling auth to EXPIRED, so prior is normally EXPIRED by Section 3); `routes/work_authorizations.py:80-82` (STEM-extension supersede is a separate ACTIVE→EXTENDED path — confirmed not touched). (c) Wording adjustment: used "controlling authorization" to match existing §3.6/§3.8 terminology; phrased supersede-from-state as permissive set "ACTIVE, EXTENDED, or already EXPIRED" (not narrowed to EXPIRED); scoped exclusion to "the just-presented `work_authorization_id`" without implying a `supersedes_id` on the new auth.
- **Item 2 — risk-score clamp test fix.** No PRD edit. Pure test-vs-PRD fixture-faithfulness correction; PRD §3.8 already covers every weight and the clamp verbatim, and the impl matches. No silence/mismatch to pin.

## Step 9: Complete PRD — 2026-06-01T20:05:00.000Z

**Source vs completed:** `PRD_FINALIZED.md` 242 lines / 40,529 chars → `PRD_COMPLETED.md` 242 lines / 41,478 chars. Char delta: **+949** (5 in-paragraph edits, no line-count change, no new sections).

**Counts:** ambiguity-pins: 4 · mismatch-revisions: 0 (one §3.6 edit bundles two related ambiguity-pins). All edits pin genuine PRD silences to behavior `implementation/` actually exhibits; no existing prose described a different behavior, so zero mismatch-revisions.

**Per-change:**
- §3.3 (Section 2 guards) — insert — ambiguity — PRD said "each chosen document must be `PRESENTED`" but never named the error; pinned that a non-`PRESENTED` chosen doc is rejected with `ERR_DOCUMENT_COMBINATION_INVALID` — `routes/onboardings.py:231-233`
- §3.6 (STEM OPT extension) — insert — ambiguity — pinned that a STEM filing with no/invalid base (missing `supersedes_id`, base not currently `ACTIVE`) is rejected with `ERR_STEM_WINDOW_MISSED`, and that an omitted `requested_gap_days` is treated as 0 with negatives floored to 0 — `routes/work_authorizations.py:48-61`, `services/calculations.py:59-65`
- §3.7 (clock test-driving) — insert — ambiguity — PRD was silent on the response body; pinned that `data` echoes `{ "current_utc": <iso8601> }` rather than a persisted entity — `routes/clock_route.py:24`
- §3.8 (risk summary, `open_tnc`) — insert — ambiguity — pinned the loose "unresolved TNC" wording to the exact predicate: `tnc_type != NONE` and onboarding not `AUTHORIZED`, false when no case — `routes/onboardings.py:142-144`
- §3.8 (risk expiring-auth term) — insert — ambiguity — pinned "controlling `WorkAuthorization`" to the onboarding's non-`SUPERSEDED` records, and "within 30 days" to the inclusive `[clock, clock+30d]` window so an already-lapsed `effective_valid_until` scores zero — `routes/onboardings.py:137-138`, `services/calculations.py:110-119`

## Pipeline complete — 2026-06-01T20:06:00.000Z

All 9 steps executed. Final state: 69/69 tests pass across all 8 parallel stability rounds under `--isolation per-test-server`. PRD documentation chain complete: `PRD.md` → `PRD_FINALIZED.md` (Step 8, §3.6 prior-auth supersede pin) → `PRD_COMPLETED.md` (Step 9, 4 residual ambiguity pins). Implementation untouched since Step 7; no re-run needed (Steps 8/9 edit documentation only).
