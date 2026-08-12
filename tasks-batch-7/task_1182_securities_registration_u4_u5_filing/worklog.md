# Worklog — task_1182_securities_registration_u4_u5_filing

## Step 1: Create task directory — 2026-08-11T00:00:00.000Z

Pre-assigned output folder `tasks/task_1182_securities_registration_u4_u5_filing` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instruction; Step 1 treated as done.

## Step 2: Generate scaffold — 2026-08-11T13:25:00.000Z

All three files exist, YAML-parse cleanly, and pass the scaffold linter with a clean verdict. The forbidden-vocabulary scan found no matches (grep exit 1 = no hits).

I notice there's a pre-existing `worklog.md` and `workspace/` directory in the task folder — these were already there (not created by me) and I left them untouched per the constraint to not disturb siblings/unknown files.

## Summary

**Task**: `task_1182_securities_registration_u4_u5_filing` — FINRA member-firm registration desk (U4/U5 filings), generated fresh from the scenario description without consulting any sibling task.

**Files written** (all verified on disk + YAML-parse + lint-clean):
- `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Complexity profile**: compliance/audit (primary) + workflow orchestration (secondary); layers = optimistic concurrency, cascading side effects, dual-variant calculation, scheduled/deferred actions; flat topology; branching state machines; segregation-of-duties role model; immediate consistency.

**Scaffold contents**:
- **15 entities**: Firm, IndividualApplicant, RegistrationRequest, JurisdictionSelection, FingerprintSubmission, BackgroundDisclosure, ExamRequirement, ExamWindow, DisclosureEvent, AmendmentFiling, TerminationFiling, U5Comment, AffiliationRequest, RenewalInvoice, RegulatoryInquiry — all FKs reverse-reachable
- **10 state machines** including: RegistrationRequest (branching + DEFICIENT↔SUBMITTED cycle + count-triggered auto-withdraw at 3), ExamRequirement (FAIL cycle + clock-driven PASSED→EXPIRED at exactly credit_expiry), TerminationFiling (FILED↔AMENDMENT_OPEN loop), plus cascades (U5 termination: depth-3 chain through affiliation revocation to invoice void)
- **5 calculations**: amendment_deadline (CALENDAR vs REGULATORY dual-variant, all literals pre-computed), renewal_fee (tiered base by firm_rank + floor-division late blocks capped at 100%, per-component rounding pinned), exam_credit_window (>= boundary at exactly +120 days), comment_accuracy_check (keyword contradiction map), deficiency_auto_withdraw (>= 3 threshold)
- **73 endpoints** including `POST /registration-desk/_clock/set_current_utc` (default 2026-05-01T00:00:00Z declared) and a full business surface; 2 OCC concurrency rules (renewal pay, registration PATCH)
- **12 errors**, **12 ordered validations** (auth → existence → duplicate → state → OCC → SoD → regulatory gate → shape → temporal → referential → fiscal), **5 roles** (RegistrationPrincipal / ComplianceOfficer with SoD, FinanceClerk, SystemOperator, Regulator — all opaque identity)

**Difficulty design (harder-than-expert)**: 18 instances, 2 per each of the 9 rules, all with fully-executed `setup_api_calls` chains (no placeholders in asserts; every numeric literal pre-computed — e.g., renewal totals 15000/10000/27500/25000, deadlines 2026-07-10 vs 2026-07-22, U5 deadline 2026-09-11, exam expiry 2026-10-01T12:00:00Z). Hard features: three-level error-precedence chains (state < SoD < regulatory gate; state < temporal), boundary pairs at exact-second and end-of-day edges, approval gated on sibling-entity exact state with clock-rollover interleaving, disjoint-window slot occupation, and invariant conservation (money and aggregate count).

**Corner design**: 36 instances across all 9 guide sections (35 active + 1 excluded_because stub), covering creation/defaults, not-found, required fields, computed fields, terminal lockdown, invalid transitions, precondition enforcement, temporal validations, RBAC denials, envelope/pagination, filtered lists, provisional-estimate non-persistence, duplicate-cycle rejection, OCC stale-version on both concurrency rules, deferred activation rollover, and immediate cascade consistency.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (73 endpoints, 15 entities, 18 + 35 instances, 572 calls scanned.)

Orchestrator verification: all three files confirmed on disk and YAML-parse cleanly (sizes 83172 / 89424 / 87305 bytes).

## Step 3: Copy shared files — 2026-08-11T13:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1182_securities_registration_u4_u5_filing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T13:40:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/workspace/PRD.md` (315 lines, 7,222 words). The two forbidden files were never opened.

## Document structure

- **§1. Introduction** — 2 paragraphs (business context of a FINRA member-firm registration desk + reader's map; `/registration-desk` mount named here, outside §3)
- **§2. Global Specifications** (10 subsections, domain-derived): 2.1 Roles/headers (all 5 roles named, all `identity: opaque` translated, `ERR_UNAUTHENTICATED`/`ERR_FORBIDDEN_ROLE`), 2.2 Response envelope (**byte-verbatim** from `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Common resource properties (all 15 entities carry `id`/`created_at`/`updated_at`/`version`), 2.5 Logical clock (fixed default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`, drives sweeps), 2.6 Deadline bases (CALENDAR vs REGULATORY, 30/15-day anchors, inclusive end-of-day, prospective basis change), 2.7 Integer-cents + per-component round-half-up, 2.8 OCC (exactly two guarded writes, both named with `ERR_STALE_VERSION`/412), 2.9 Segregation of duties (all six guarded actions), 2.10 Twelve-priority validation cascade with each check's `applies_to` scope enumerated
- **§3. Business Logic** (9 subsections, chronological lifecycle grouping): onboarding → drafting U4 → fingerprints/disclosure review → exams/windows/credit expiry → submission/deficiency/approval gate → disclosure events/amendments → renewals → affiliations → U5/comments/inquiries
- **§4. Endpoint table** — 73 rows, 4 columns only (Method, Path, Description, Authorized Role(s)); 201/200 status rule stated above the table
- **§5. Error catalogue** — 12 rows, 2 columns only, no trigger conditions

## Hard Contract reports

```
Field coverage check:
- entities[].fields + endpoints[].input/query/path identifiers: 71 required, 71 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: 12 checked, 12 expressed as an explicit ordered cascade in §2.10, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_*_version + ERR_STALE_VERSION/412 in §2.8, §3.2, §3.7), 0 missing
- state_machines[].transitions: 27 checked across 10 machines, all from/to states, preconditions (paired with error ids), and side effects expressed — including full termination cascade with the affiliation-revocation sub-cascade voiding second-firm ISSUED invoices, 0 missing
- calculations[]: 5 checked, 5 expressed in precise prose (amendment_deadline both bases + anchors/day-counts/inclusive boundary; renewal_fee rank logic, 10000/5000 base, 5000/0 jurisdiction fees, 25%-per-14-day-block capped at 100%, per-component round-half-up, provisional_estimate vs final_invoice + payable_total_cents; exam_credit_window 120 days with inclusive >= boundary; comment_accuracy_check full 4-reason keyword map with 0/≥1 disposition boundary; deficiency_auto_withdraw third-return-withdraws boundary), 0 missing
- validations[] conditions: 12 checked, all 12 matchable to their error_id in §2.10/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (submitter_user_id stamping, exam cascade on first submit only, fee lock on APPROVED, relinquish recompute, inquiry count recompute on open/route/respond, RETURNED-row immutability with re-filing creating a new row), 0 missing
- entities[].fields[] structured content: all 71 fields placed on owning entities with types/defaults/derivations (e.g., fingerprint_required derived-on-read, review_status CLEARED-at-creation for answer=false, open_inquiry_count set membership), 0 missing
- sibling-branch symmetry: DRAFT/DEFICIENT/SUBMITTED withdraw siblings, approve/deny/return exits, CLEARED/REJECTED fingerprint outcomes, PASS/FAIL/NO_SHOW results, AMENDED/LATE_AMENDED pair — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 437
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot-checks passed: all 12 error ids, all 35 state values, and all enum values (`RR/IA/PRINCIPAL`, `SIE/S7/S63/S66/S24`, `FINRA/NYSE/NASDAQ`, question/event/termination/subject-filing enums, `COMPLIANCE_OFFICER`/`REGISTRATION_PRINCIPAL` author_role values) appear verbatim; no pseudocode operators or fuzzy/approximating words in prose.

Orchestrator verification: PRD.md on disk, 315 lines / 54053 bytes.

## Step 5: Generate unit tests — 2026-08-11T14:10:00.000Z

Done. Full generation complete and verified.

## Summary

**Output tree** (under `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/`):

`test_helpers/` (9 files):
- `types.py` — 15 entity TypedDicts + 20 status/role enums (all entities carry the PRD §2.4 common set)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (clock, firms, applicants, registration-requests + 6 actions + estimate, jurisdiction-selections, fingerprints, disclosures, exam-requirements/-windows, disclosure-events, amendment-filings, termination-filings, u5-comments, affiliation-requests, renewal-invoices, regulatory-inquiries)
- `api_errors.py` — `ApiErrorId` (12 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (uses `is_valid_uuid` / `is_iso8601_timestamp`; invoice invariant enforces total = sum of pinned components)
- `factories.py` — input-only payload factories with auto-unique CRD numbers
- `constants.py` — deadline windows (30/30/15), exam credit (120d), fee schedule (10000/5000/5000/0), late blocks (14d/25%/100% cap), MAX_DEFICIENCIES=3, min lengths
- `test_users.py` — 5 opaque-role shared headers + per-user builders for SoD tests
- `fixtures.py` — composite tiers: `create_firm_applicant_request`, `create_submitted_request`, `create_active_registration` (full gate: fingerprint CLEARED + all submit-created exams passed, SIE-first, approve + next-day clock rollover), `create_active_registration_with_invoice`, `create_terminated_registration`, plus helpers (`pass_exam_requirement`, `file_amendment`, `set_clock`, getters)
- `__init__.py` — barrel export

`test_suite/` (5 files, 71 tests): `conftest.py` + `test_01_onboarding_and_access.py` (21), `test_02_registration_lifecycle.py` (20), `test_03_deadlines_and_amendments.py` (12), `test_04_renewals_affiliations_occ.py` (18).

**Coverage (design-index-only contract):**
- Queue A (Difficulty): 18/18 instances, each with exactly ≥2 tests (36 tests)
- Queue B (Corner): 35/35 non-stub instances, each ≥1 test; the single `excluded_because` stub (`Corner/calculations/comment_accuracy_consistent_passes`) correctly untranslated, cross-reference verified
- **Instances skipped: none** — every instance passed the PRD-first two-condition filter

**Verifications on disk:**
- `python -m py_compile` clean on all 15 files
- Design-tag audit: every one of the 71 tests carries exactly one `Design:` tag on the last docstring line; all 71 tags resolve to real instances in the source YAMLs; zero untagged/dual-tagged/dangling tags
- Verbatim-citation sweep: all 115 quoted PRD fragments grep literally in `workspace/PRD.md`
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/section-table references in comments
- `pytest --collect-only`: **71 tests collected, 0 errors**

**Notable PRD-fidelity decisions:**
- `occ_stale_version_on_invoice_pay` asserts `ERR_INVALID_STATE` (not `ERR_STALE_VERSION`) on the replayed pay, per the instance's own note and PRD §2.10 ordering (state legality step 5 precedes OCC step 6)
- Priority-pair tests (`state_vs_business_safety_on_approve`, `state_vs_temporal_on_termination_filing`) are covered because PRD §2.10 explicitly makes the check ordering part of the contract ("when several problems exist at once, the check earliest in this order determines the error returned")
- All date arithmetic in the indices was independently recomputed and matches (e.g., REGULATORY 2026-06-10 + 30bd = 2026-07-22; 2026-07-31 + 30bd = 2026-09-11; inquiry 2026-08-03 + 15bd = 2026-08-24; credit 2026-06-03T12:00Z + 120d = 2026-10-01T12:00Z)
- Segregation-of-duties tests thread distinct `X-User-ID`s via `make_user_headers` so the SoD check passes except where it's the assertion target

## Step 6: Generate implementation — 2026-08-11T14:10:30.000Z

All verifications pass. Final summary:

## Implementation complete

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/workspace/implementation/`):

- `start.sh` — executable, foreground, `exec python3 app.py`, guarded `pip install` (no-op once flask importable), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — entry point, ApiError/404/405/500 envelope handlers, blueprint registration (Flask built-in `/static` route disabled via `static_folder=None`)
- `db.py` — in-memory `Store` (15 dicts keyed by id), logical clock fixed at `2026-05-01T00:00:00Z` at boot, global insertion sequence. **No seeding anywhere** — store starts empty on every boot
- `errors.py` — `ApiError` + constructors for all 12 catalog error IDs with their exact HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type` object/array/error, `data{error_id, message}` for errors
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 5 roles, 401/403 split
- `timeutil.py`, `common.py` — logical-clock accessors, ms-precision ISO formatting, body/existence/field/enum/pagination helpers, `version`+`updated_at` mutation touch, serializers
- `services.py` — deadline calc (CALENDAR/REGULATORY, end-of-day 23:59:59.999Z), renewal fee (rank/base/surcharge with Decimal ROUND_HALF_UP, per-component-then-sum), payable recompute, clock sweeps (APPROVED→ACTIVE rollover before PASSED→EXPIRED credit sweep, `>=` boundary), withdraw/terminate cascades (selections, invoice voids, affiliation revocations + second-firm invoice voids), comment-accuracy keyword map, deficiency auto-withdraw at count ≥ 3
- `routes/` — 15 modules covering all resource groups

**Route diff**: 73 declared in SCAFFOLD.yaml §1.5, 73 registered — CLEAN (zero missing, zero extra).

**Boot check**: passed on fresh processes across 3 launches — server responds within ~1.5s; unknown route → enveloped `ERR_NOT_FOUND` 404; missing auth → `ERR_UNAUTHENTICATED` 401; fresh boot confirms empty store and clock back at default.

**Functional smoke tests passed**: full DRAFT→SUBMITTED→APPROVED→ACTIVE lifecycle (exam spawn per category, window PASS with credit_expiry = pass+120d, SoD on approve, day-rollover activation), jurisdiction fee 5000/0 schedule, REGULATORY deadline arithmetic hand-verified (May 4 2026 + 30bd = Jun 15; +15bd = May 25), amendment filing with SoD accept, U5 cascade to TERMINATED, comment contradiction scoring, inquiry open→route→respond→close with `open_inquiry_count` tracking, inquiry blocking U5 open-amendment, third-deficiency auto-withdraw with RELINQUISHED cascade, exam credit EXPIRED sweep enabling deny, invoice components 5000+10000+10000=25000 with OCC pay and 409 on replay.

**Judgment calls on PRD-silent points** (flagged for review): submit without a SELECTED jurisdiction and deny without cause both return 409 `ERR_INVALID_STATE` (state-machine precondition failures); the third-return auto-withdraw applies the WITHDRAWN cascade (selections→RELINQUISHED, ISSUED invoices→VOID) per the JurisdictionSelection state machine's "transitions to WITHDRAWN" trigger; `deadline_basis` is serialized on Firm since PATCH accepts it and tests need to observe it; `submitter_user_id` is serialized on RegistrationRequest (PRD §2.9 names it) while amendment/U5 filer ids stay internal.

## Step 7: Run tests and iterate — 2026-08-11T14:30:00.000Z

Two consecutive clean 8-round parallel sweeps (16 rounds total, 71/71 passed, 0 failed, 0 errors in every round).

**Summary**

- **Iterations run:** 4 sweeps total — sweep 1 (baseline: 1 deterministic failure × 8 rounds), sweep 2 (test fix verified the assertion; surfaced infra restart-storm flakes in 7/8 rounds), sweeps 3–4 (both fully clean after boot-hardening; sweep 4 was a confirmation run).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/test_suite/test_03_deadlines_and_amendments.py` — `TestDeadlineBasisVariants::test_amendment_deadline_regulatory_basis`: setup created a firm and an applicant with no PRD-sanctioned link between them, then patched the firm's `deadline_basis` and asserted the disclosure event's `amendment_due_at` used REGULATORY business-day counting. PRD §3.6 computes the deadline "under the firm's configured deadline basis," but the applicant model (§3.2) has no `firm_id` — with no registration the governing firm is underdetermined (implementation's registration-based resolution → CALENDAR default is PRD-faithful, so the test failed with `2026-07-10` vs expected `2026-07-22`). Fixed the setup to build a full ACTIVE registration via `create_active_registration()` (the only PRD-sanctioned applicant↔firm link) before patching that registration's firm. The exact-date assertion `2026-07-22` (= 2026-06-10 + 30 business days) is unchanged and now uniquely derivable from PRD §2.6/§3.6.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/workspace/implementation/start.sh` — replaced the per-restart `python3 -c "import flask"` guard with a one-time sentinel (`~/.cache/task_1182_deps_ok`), eliminating one full Python cold-start per server boot (568 boots per sweep). This addressed the runner's "API server could not be restarted" setup errors (15s readiness-poll exhaustion) that appeared under the synchronized 8-round boot storm in test_02's heavy-lifecycle region. No API behavior changed; storage remains in-memory only.
  - Harness note: the sweep script `/tmp/sweep_1182.sh` also staggers round launches by 2s each to decorrelate boot storms; rounds still overlap for the vast majority of their ~90s wall time.

Orchestrator verification: all 8 `results.{1..8}.json` re-read from disk — each reports passed=71, total=71, failed=0, errors=0. ALL_CLEAN.

## Step 8: Finalize PRD — 2026-08-11T14:40:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1182_securities_registration_u4_u5_filing/workspace/PRD_FINALIZED.md` written with a single inline revision.

**Line counts / delta:** PRD.md 315 lines, PRD_FINALIZED.md 315 lines — 0% line-count delta; exactly one paragraph (line 184, §3.6) revised inline. No sections added or removed.

**Changes (one bullet per change):**
- §3.6 — revise — pinned the governing firm for a disclosure event's `amendment_due_at`: resolved at event-creation time as the firm of the applicant's currently `ACTIVE` registration request (most recently activated by `approved_at`, ties by `created_at` ascending — the same resolution §3.6 already specifies for the amendment filing's `registration_request_id`), with the `CALENDAR` basis applying when the applicant has no `ACTIVE` registration — `implementation/services.py:96-101` (`event_firm_basis`), `services.py:83-93` (`applicant_active_registration`), callsite `routes/events.py:37-47`.

**Step 7 diff items requiring no edit:**
- `start.sh` sentinel fix — pure infrastructure (boot-time dependency check), no API behavior change; no PRD edit.
- The test fix itself was the evidence for the §3.6 silence above; the test's post-fix expectation (REGULATORY counting once an ACTIVE registration links applicant to the patched firm) is exactly what the pinned rule now states.

**Per-edit pre-edit search log:**
- Edit 1 (§3.6 governing-firm rule):
  - (a) Subject: which firm's `deadline_basis` governs a disclosure event's `amendment_due_at`, and when it is resolved.
  - (b) Enumerated impl paths (all read/grepped): `routes/events.py:37-47` (creation: resolves basis, computes deadline, stores `_deadline_basis`); `services.py:96-101` (`event_firm_basis`: ACTIVE-registration resolution, `CALENDAR` fallback); `services.py:83-93` (`applicant_active_registration`: `approved_at`-max, `created_at`-ascending tie-break; shared with amendment-filing creation at `routes/amendments.py:34`); `services.py:76-80` (`firm_basis`: reads the firm's current `deadline_basis`); `routes/amendments.py:103-105` (amendment-return recompute reuses the creation-time stored basis); `routes/terminations.py:53-54` (U5 `filing_deadline_at` uses the request's own firm — unambiguous, wording untouched); `routes/inquiries.py:62` (always `REGULATORY` — already pinned in §2.6, untouched); `routes/firms.py:43,73-77` (CALENDAR default + patchability — already pinned in §2.6/§3.1); §3.8 dual registration confirms multiple ACTIVE registrations per applicant are possible (covered by the tie-break clause).
  - (c) Wording adjustment: pinned resolution explicitly "at event-creation time" so the existing §3.6 sentence about the return path ("recomputed … under the same deadline basis") remains consistent with `amendments.py:103-105`, which reuses the creation-time basis rather than re-resolving; reused §3.6's own pre-existing tie-break phrasing so the two callsites of the shared resolver (`events.py` and `amendments.py`) are described identically.

## Step 9: Complete PRD — 2026-08-11T14:55:00.000Z

Done. `PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size:** source 315 lines / 54,565 chars → completed 317 lines / 59,120 chars (char-delta +4,555; +2 lines from the two paragraph splits in §2.8).

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 edits total).

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.3 — insert — ambiguity — pinned pagination validation (`ERR_INVALID_REQUEST` for non-integer/out-of-range limit/offset) and enumerated the exact filter query params per list endpoint (firms/applicants have none; `cycle_year` filter must be an integer) — common.py:83-118 and each routes/*.py `list_page` call.
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — common.py:50-59.
- §2.4 — insert — ambiguity — client-supplied dates/timestamps (`date_of_birth`, `event_date`, `termination_date`, `window_start`, `window_end`) stored and returned verbatim — exams.py:126-127, events.py:42, terminations.py:59, applicants.py:44.
- §2.5 — revise — ambiguity — clock may be set to any instant (not only forward), missing/unparseable `to_iso8601` is `ERR_INVALID_REQUEST`, `current_utc` echoes the supplied string verbatim — clock.py:15-28.
- §2.5 — revise — mismatch — sweep order pinned as activation-rollover first, then credit-expiry sweep (PRD had listed expiry first; impl's order locks credits of same-set activations) — services.py:160-178.
- §2.8 — insert — ambiguity — omitted expected-version field → `ERR_INVALID_REQUEST` (400); present-but-mismatched/non-integer → `ERR_STALE_VERSION` (412) — registration_requests.py:103-107, renewals.py:96-101.
- §2.9 — insert — ambiguity (flagged call) — amendment/termination filer ids are internal-only (never serialized); `submitter_user_id` is serialized on RegistrationRequest (null until first submission) — amendments.py:47, terminations.py:64, registration_requests.py:67,134, common.py:68-80.
- §3.1 — insert — ambiguity (flagged call) — `deadline_basis` (`CALENDAR` at birth) is serialized on every firm response — firms.py:19-20,38-46.
- §3.2 — insert — ambiguity — background disclosures may be created against a request in any status (no parent-state precondition) — background.py:19-45.
- §3.2 — insert — ambiguity — relinquishment echo also recomputes each affected ISSUED invoice's `total_cents` (new jurisdiction + pinned base + pinned surcharge) — services.py:218-225.
- §3.3 — revise — ambiguity — fingerprint capture allowed regardless of parent request status; `rejection_reason` recorded verbatim, null when omitted — fingerprints.py:19-35,70-71.
- §3.4 — insert — ambiguity — ad-hoc exam requirements may be added whatever the request's current status — exams.py:27-50.
- §3.5 — insert — ambiguity (flagged call) — first submission with no SELECTED selection → `ERR_INVALID_STATE` (409); resubmission from DEFICIENT does not re-check the selection rule — registration_requests.py:120-131.
- §3.5 — insert — ambiguity (flagged call) — third-return auto-withdraw applies the full WITHDRAWN cascade (SELECTED selections → RELINQUISHED, ISSUED invoices → VOID) — registration_requests.py:195-201, services.py:189-194.
- §3.5 — insert — ambiguity (flagged call) — denial without a FLAGGED disclosure or EXPIRED exam → `ERR_INVALID_STATE` (409), checked before segregation-of-duties — registration_requests.py:212-225.
- §3.6 — insert — ambiguity — amendment-return recomputes `amendment_due_at` under the basis remembered at event creation, unaffected by later firm reconfiguration — amendments.py:99-106, events.py:46.
- §3.7 — insert — ambiguity — renewal estimate takes `cycle_year` as a query parameter (integer 2026-2100 else `ERR_INVALID_REQUEST`) and is available for a request in any status — registration_requests.py:247-266.
- §3.7 — revise — ambiguity — `payable_total_cents` is exposed on every invoice response (create/read/list/pay/void), recomputed as of the call — renewals.py:22-23.
- §3.8 — insert — ambiguity — affiliation approval failure errors pinned (first registration not ACTIVE → `ERR_INVALID_STATE`; same-firm → `ERR_REFERENTIAL_VIOLATION`; competitor → `ERR_DUPLICATE`); denial requires a `denial_reason` string (else `ERR_INVALID_REQUEST`) — affiliations.py:85-116.
- §3.9 — revise — mismatch — removed the claim that a U5's `termination_reason`/narrative fields "may be amended" while AMENDMENT_OPEN (no such endpoint exists); pinned that opening changes only status and that blocked open/close-amendment attempts return `ERR_INVALID_STATE` (409) — terminations.py:94-117 (no PATCH route).
- §3.9 — insert — ambiguity — U5 comments may be added in any filing status — comments.py:22-37; U5 close precondition failures → `ERR_INVALID_STATE` (409) ahead of the segregation check — terminations.py:120-134; inquiry creation validates `subject_filing_type`/required fields before resolving subject existence (reversed §2.10 order on this endpoint) — inquiries.py:43-53.

All other impl behaviors (fee formulas, deadline arithmetic, contradiction map, cascades, gate conditions, OCC scope, validation cascade order) were already uniquely pinned by the PRD and verified against the code with no change needed.
