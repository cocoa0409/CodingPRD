# Worklog — task_1255_banking_access_safe_account_enrollment

## Step 1: Create Task Directory — 2026-08-12T00:00:00.000Z

Task directory `tasks/task_1255_banking_access_safe_account_enrollment/` and its `workspace/` subdirectory were pre-assigned and already exist. Step 1 treated as done (no auto-index scan run, per instructions).

## Step 2: Generate Scaffold — 2026-08-12T10:27:00.000Z

All three scaffold artifacts are generated, verified on disk, and pass `scaffold_lint.py` with a clean verdict.

## Summary

**Task**: `task_1255_banking_access_safe_account_enrollment` — Bank On coalition program (compliance_audit × workflow_orchestration, flat topology, cyclic state machines, segregation_of_duties role model; difficulty pushed past the Expert band per the difficulty parameter).

**Output files** (all non-empty):
- `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/SCAFFOLD.yaml` (87 KB) — §1.0–§1.7 only, no design keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (86 KB) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/SCAFFOLD_CORNER_DESIGN.yaml` (135 KB) — single top-level key `scaffold_corner_design`

**Counts**:
- Entities: **13** (AccountStandard, PartnerInstitution, CertificationReview, Participant, Referral, AccountOpeningEvent, AccountApplication, BarrierCase, EducationPairing, RetentionCheckpoint, FundingGrant, PartnerReport, OutreachCampaign)
- State machines: **13** (one per entity; cyclic on PartnerInstitution recert, BarrierCase negotiation, PartnerReport rework, Referral book/unbook, Application decline/reinstate)
- Endpoints: **60** (incl. `POST /api/ops/evaluate-due` epoch and `POST /api/_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z)
- Errors: 28; calculations: 10; validations: 10 priority tiers; roles: 5 (2 entity-backed); OCC concurrency rules: 2 (review-create vs institution version, report-create vs grant version)
- Difficulty design instances: **18** (9 rules × 2; all with structured, replay-checked `setup_api_calls`/`trigger` chains and literal-computed asserts, e.g. per-account-then-sum rounding 14889 vs 14888, retention PROVISIONAL 1.0/14926¢ vs FINAL 0.5/9926¢, score exactly 90.00 PASS vs 88.75 CONDITIONAL)
- Corner design instances: **47** active + 1 `excluded_because` stub, across all 9 taxonomy sections; every error code in the catalog has at least one triggering recipe

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (697 calls scanned; two FK_REVERSE_UNREACHABLE findings during the pass were fixed by adding a `current_review_id?` filter to the institutions list and a filtered `GET /api/account-opening-events` list.)

## Step 3: Copy Shared Files — 2026-08-12T10:27:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1255_banking_access_safe_account_enrollment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T10:33:00.000Z

PRD.md exists at 52,837 bytes / 294 lines.

## Summary

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/workspace/PRD.md` from the scaffold without consulting either difficulty/corner design file.

**Structure:**
- §1 Introduction (2 paragraphs — coalition mission + population served + logical-clock rationale)
- §2 Global Specifications (10 subsections): 2.1 RBAC + identity translation, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Epoch, 2.6 OCC on Parent Anchors, 2.7 Monetary Precision, 2.8 Conserved Quantities (grant ledger + event seats), 2.9 Nested Resource Retrieval, 2.10 Validation Ordering
- §3 Business Logic & Workflows (10 subsections): 3.1 Standards & Certification Cycle, 3.2 Institutions Suspend/Lapse/Reinstate, 3.3 Participants/Docs/Referrals, 3.4 Pipeline Derivation, 3.5 Events & Booking, 3.6 Applications/Decisions/Barrier, 3.7 Retention Checkpoints, 3.8 Education Pairings, 3.9 Grants/Reports/Claim Computation, 3.10 Outreach Campaigns
- §4 Endpoint table (60 rows, 4 columns)
- §5 Error catalogue (28 rows, 2 columns)

**Hard Contracts (all PASS):**
- Contract 1 Field-Name Coverage: 97 required / 97 present / 0 missing
- Contract 2 Rule Coverage: 42/42 spot-checks pass — priority ordering phrase, both OCC rules with `expected_institution_version`/`expected_grant_version` + `ERR_STALE_VERSION`, 4-link decert cascade, grant-suspend cascade, barrier-accept cascade, all state-machine enum values across 13 entities, all calculation constants (rubric weights/thresholds 90.00/75.00/85.00/70.00; tier grosses 5000/7500/10000; withholding 75bps with the 14889-vs-14888 rounding-order worked example; bonus tiers 0.80/0.60 with 2500/1500; stipend 10% on 0.5 floor; offsets 183/365/30; review gap 30d; campaign budget cap 500000; coach caseload 3; certification expiry 24 months), all 28 error IDs present in prose, all 5 roles, all enum value sets (charter, rubric, evaluation mode, course codes, prior banking record, doc types, created_via, decline reasons, checkpoint kinds, criteria names), clock default `2026-05-01T00:00:00Z`, ops epoch output field names
- Contract 3 §3 Path Purity: 626 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos

**Key scattering decisions:** endpoint inputs distributed across §3 subsections (e.g., application `outcome`/`decline_reason`/`chex_flagged` separated from `participant_id`/`institution_id`/`id_type_presented`; report `evaluation_mode` in §3.9 separated from grant-ledger rules in §2.8); numeric constants embedded in narrative ("three" for caseload, "thirty days" for review gap, basis-point withholding); no foreign keys declared — relationships expressed via action narrative; sibling decline branches (CHEX / INSUFFICIENT_ID / OTHER) rendered with equal density.

## Step 5: Generate Unit Tests — 2026-08-12T10:58:00.000Z

Done. Full test infrastructure generated for task_1255.

## Files created

**`test_helpers/`** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/test_helpers/`
- `types.py` — 13 entity TypedDicts (all carry common fields), 20 status/enum classes, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with 48 methods covering every PRD §4 endpoint (paths carry the `/api` prefix; per-request connection close for per-test-server isolation)
- `api_errors.py` — all 28 `ApiErrorId` codes with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_grant_ledger_invariant`
- `factories.py`, `constants.py` (all scoring/tier/cap/clock constants), `test_users.py` (opaque shared constants + per-instance builders for entity-backed `InstitutionOfficer`/`Participant` and distinct admin IDs for SoD)
- `fixtures.py` (~600 lines) — composite builders: `setup_certified_institution`, `setup_scored_review`, `setup_rubric_divergence`, `setup_two_institutions_scored`, `setup_decertification_pending`, `setup_submitted_application`, `setup_opened_account`, `setup_declined_chex_case`, `setup_report_ready`, `setup_two_account_retention_scenario`, `setup_event_with_referrals`, clock/epoch drivers
- `__init__.py` barrel

**`test_suite/`** — `conftest.py` + 9 test files (`test_01` envelope/errors → `test_09` campaigns), 83 tests total.

## Coverage
- **Queue A (Difficulty): 36 tests** — all 18 instances × 2 tests each, every test tagged `Design: Difficulty/<rule_id>/<instance.name>`
- **Queue B (Corner): 47 tests** — all 47 non-stub instances × 1 test, tagged `Design: Corner/<section>/<instance.name>`
- **Skipped: 1** — `Corner/calculations/mandatory_floor_fail_is_covered_by_difficulty` is an `excluded_because:` stub; its pointer to `certification_score_mandatory_floor_branch` resolves. No other instance skipped; no skip/xfail markers anywhere.

## PRD-first adjustments (unique-derivability, not weakening)
- `account_standard_creation_defaults` / `response_envelope_success_shape`: assert UUID/ISO-format/int-version instead of `version == 1` / `created_at == clock default` — PRD pins neither version's initial value nor created_at to the logical clock.
- `application_create_safety_vs_referential`: P1's docs changed to VERIFIED STATE_ID without PROOF_OF_ADDRESS (recipe's SUBMITTED-POA + STATE_ID combo would let ERR_ALT_ID_NOT_ACCEPTED race ERR_DOCS_INCOMPLETE inside the same priority-7 band, which PRD §2.10 does not order).
- `campaign_zip_cluster_half_open_overlap`: dropped "only 2 ACTIVE campaigns exist" — PRD defines no campaign list endpoint (unobservable).
- OCC tests assert relative increments (`captured + 1`) instead of absolute `version == 2/3`.
- `non_monotonic_clock_rejected`: clock-still-at-default proven by a successful set to exactly the default (no clock-read endpoint exists).

## Verification results
- `python -m py_compile` on all 19 files: **OK**
- `pytest --collect-only`: **83 tests collected**, no import errors
- Custom audit script: every test has exactly one Design tag; all tags resolve to real instances; difficulty ≥2/instance and corner ≥1/instance confirmed; every docstring's PRD quote survives verbatim containment against PRD.md (whitespace-normalized).

## Step 6: Generate Implementation — 2026-08-12T10:58:30.000Z

Isolation confirmed. Note the created_at uses the logical clock default (2026-05-01) per PRD §2.5 — timestamps derive from the logical clock, which is correct.

All four verification gates pass. Summary:

## Summary

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/workspace/implementation/`):

- `start.sh` — executable, guarded pip install, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app, blueprint registration, ApiError/404/405/500 handlers using the envelope
- `db.py` — in-memory stores (13 dicts, all empty at boot), logical clock (default `2026-05-01T00:00:00Z`, monotonic set), date/datetime parsing, `add_months` for the 24-month certification expiry
- `errors.py` — all 28 error IDs from the catalog with exact HTTP statuses (incl. 402 INSUFFICIENT_GRANT_FUNDS, 412 STALE_VERSION, 422 trio)
- `response.py` — envelope `{meta:{api_request_id, api_request_timestamp}, response_type, data}`, pagination fields `limit/offset/total_count/has_more` in `meta` for lists, defaults 10/0, min 1, max 100
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), role gating (403), body/field/enum validators (400)
- `services/common.py` — common fields (`id` UUID, `created_at`/`updated_at` 3-frac-digit ISO, `version`), docs_complete derivation, pipeline-stage precedence recomputation
- `services/calculations.py` — Decimal-based certification score (weights 0.25/0.20/0.15/0.20/0.20, 2dp ROUND_HALF_UP, dual rubric thresholds, mandatory floor), retention rates (4dp, null on empty eligible, PROVISIONAL vs FINAL numerator sets), pinned 7-step claim computation (per-account rounding before summing, M6-primary bonus tier, pre-stipend-base education stipend)
- `routes/standards.py`, `institutions.py`, `reviews.py` (OCC + 30-day gap + supersede + SoD + decert cascade), `participants.py`, `referrals.py`, `events.py` (window overlap, capacity, roster, cancel cascade), `applications.py` (referral/event linkage, alt-ID gate, barrier gate, education gate, checkpoint pair creation, campaign spend on conversion), `barrier_cases.py` (propose/counter/accept/escalate with 3-round escalation rule), `education.py` (caseload cap 3, follow-up gating), `checkpoints.py` (list/get + `ops/evaluate-due` epoch: checkpoints by due_date/created_at, certification lapse, event completion, follow-up due), `grants.py` (ledger conservation, suspend cascade, close guard), `reports.py` (OCC on grant version, claim snapshot, cap/funds checks, reserve/disburse/release movements, REJECTED-resubmit recompute), `campaigns.py` (half-open overlap, 500000-cent cluster cap), `clock.py`

**Endpoint count:** 60/60 (method, path) pairs registered — diff against SCAFFOLD §1.5 endpoint table is IDENTICAL.

**Boot checks:** all Python files compile; `start.sh` is executable; server boots on `PORT`, responds with correct envelope, enforces auth; fresh-reboot isolation verified (store empty on second boot); end-to-end smoke test passed covering standard activation/supersession, OCC 412, review supersede, SoD 409, certification, participant docs, referral booking, application approve with checkpoint creation, barrier negotiation through 3 counters to accept/REINSTATED/approve, coach caseload/ownership, follow-up gating + epoch transition, monotonic clock rejection, campaign overlap/budget-cap rejections, and grant ledger conservation (4963-cent single-account claim verified against the pinned rounding order).

One interpretation call worth flagging: review creation is allowed from `UNDER_REVIEW` in addition to `APPLIED/LAPSED/CERTIFIED`, because the PRD's supersede-on-create semantics and the OCC stale-version rule both require a second create while a live review exists to be a valid path (with the stale-version error surfacing per the OCC priority when the version doesn't match).

## Step 7: Run Tests and Iterate — 2026-08-12T11:10:00.000Z

All 8 rounds pass 83/83. Clean sweep — exiting. (Orchestrator verified on disk: results.1..8.json all show passed=83/83, failed=0.)

## Summary

- **Iterations run:** 2 (first sweep: 81/83 in all 8 rounds; second sweep after fix: 83/83 in all 8 rounds).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/test_helpers/fixtures.py`, fixture `open_review()` — reordered two lines: the `inst_id = institution["id"] if isinstance(institution, dict) else institution` normalization now happens **before** the `get_institution(institution["id"])["version"]` OCC-version lookup. The original order dereferenced `institution["id"]` on a raw string id, raising `TypeError: string indices must be integers, not 'str'` whenever a caller passed a string (as `_run_recertification_cycle` does). One-line why: helper crashed on its own documented string-id call path before any assertion ran — pure test-artifact bug, no PRD rule involved.

- **Fixes applied to `implementation/`:** None — the implementation was correct; both failing tests (`test_suspend_then_reinstate_before_expiry`, `test_lapse_then_recertification_review_recertifies` in `test_03_institution_lifecycle.py`) traced verbatim to PRD §3.1/§3.2 (suspend/reinstate-before-expiry, epoch-driven lapse, LAPSED→UNDER_REVIEW recertification, finalize→CERTIFIED with `certified_at` = clock reading), and the failure was entirely the helper ordering bug above.

## Step 8: Finalize PRD — 2026-08-12T11:15:00.000Z

Verification complete. All four behaviors exercised by the two initially-failing tests are verbatim-pinned by the PRD and matched exactly by the implementation; the only Step 7 fix was a pure test-artifact ordering bug with no PRD consequence. `PRD_FINALIZED.md` is therefore a verbatim copy of `PRD.md`.

## Summary

**Line counts:** PRD.md = 294 lines; PRD_FINALIZED.md = 294 lines; delta = 0 lines, 0.0%. Byte-identical (diff: no output).

**Changes:** None. Per the method's escape hatch — the step_7_diff contains 0 implementation/ fixes, 0 test deletions, and exactly one `test_helpers/` fix explicitly marked "no PRD rule involved" — after inspection I confirmed there is genuinely nothing to pin, so PRD_FINALIZED.md remains a verbatim copy of PRD.md.

**Pre-edit search log (candidate edits evaluated, all rejected):**

- **(a) Subject: suspend → reinstate-before-expiry** (from `test_suspend_then_reinstate_before_expiry`)
  **(b)** Read `implementation/routes/institutions.py` (suspend L67-77: CERTIFIED-only else ERR_INVALID_STATE; reinstate L79-92: SUSPENDED-only else ERR_INVALID_STATE, `clock >= certification_expires_at` → ERR_CERTIFICATION_LAPSED, both `touch()`-increment version). Cross-checked PRD §3.2 prose, which pins every one of these behaviors verbatim, including "strictly before" and the version increments.
  **(c)** No wording change — PRD already uniquely determines the behavior; impl matches.

- **(a) Subject: epoch-driven lapse (including exact-expiry boundary and SUSPENDED-not-lapsed)**
  **(b)** Read `implementation/routes/checkpoints.py` L79-87: epoch lapses only `CERTIFIED` institutions when `clock_dt >= certification_expires_at`, increments `certifications_lapsed`. PRD §3.2 pins "finds a `CERTIFIED` institution whose `certification_expires_at` has been reached" — the "reached" phrasing and CERTIFIED-only scope match the impl exactly, as corroborated by `test_lapse_fires_exactly_at_expiry` and `test_reinstate_at_or_after_expiry_rejected`.
  **(c)** No wording change.

- **(a) Subject: LAPSED → UNDER_REVIEW recertification review open**
  **(b)** Read `implementation/routes/reviews.py` L70-73 (create allowed from APPLIED/LAPSED/CERTIFIED/UNDER_REVIEW), L118-121 (institution set to UNDER_REVIEW, `current_review_id` assigned), L79-88 (30-day gap, equality allowed — consistent with the recert review's 2026-04-01 start after prior period_end 2026-02-28). PRD §3.1 pins all of this verbatim ("a `LAPSED` institution likewise moves to `UNDER_REVIEW`", gap rule with equality).
  **(c)** No wording change.

- **(a) Subject: finalize → CERTIFIED with `certified_at` = logical-clock reading, expiry = +24 months**
  **(b)** Read reviews.py L189-228 (`inst["certified_at"] = db.now_iso()`; `certification_expires_at = db.add_months(parse_dt(get_clock()), 24)`; `certified_standard_id` = pinned standard; FAIL branch runs the four-link decert cascade) and `implementation/db.py` L57-59 (`now_iso()` reads the logical clock, never wall clock). PRD §3.1 pins this verbatim ("`certified_at` is set to the current logical-clock reading, `certification_expires_at` is computed as `certified_at` plus twenty-four months").
  **(c)** No wording change.

- **(a) Subject: the actual Step 7 fix — `open_review()` fixture line ordering** in `test_helpers/fixtures.py` L94-105 (string-id normalization now precedes the `get_institution(...)["version"]` OCC lookup; current file shows the fixed order). **(b)** Confirmed caller `_run_recertification_cycle` (test_03_institution_lifecycle.py L31-32) passes a raw string id. **(c)** No PRD edit possible — the PRD governs server behavior, not test-fixture argument normalization; the step_7_diff itself marks this "no PRD rule involved."

One observation deliberately left unpatched per HARD SCOPE: the impl rejects review creation on a `DECERTIFIED` institution with ERR_INVALID_STATE (reviews.py L72), which the PRD never explicitly enumerates — but this choice was not exercised by any Step 7 fix, so it is outside the permitted edit scope.

## Step 9: Complete PRD — 2026-08-12T11:27:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1255_banking_access_safe_account_enrollment/workspace/PRD_COMPLETED.md` produced.

## Summary

**Size**: PRD_FINALIZED.md 294 lines / 52,837 chars → PRD_COMPLETED.md 294 lines / 55,967 chars. Char delta **+3,130**, zero lines added/removed (all in-paragraph inserts/revisions; no new sections).

**Counts**: 17 ambiguity-pins, 9 mismatch-revisions (26 edit operations across 25 lines; one line carries two edits).

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as wall-clock, not logical clock — implementation/response.py:15-16
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_VALIDATION` — implementation/response.py:78-93
- §2.4 — insert — ambiguity — `version` starts at 1 on creation; `created_at`/`updated_at` stamped from the logical clock — implementation/services/common.py:7-21, implementation/db.py:57-64
- §2.5 — insert — ambiguity — clock set returns 200 with `{"current_utc": "<new reading>"}` — implementation/routes/clock.py:23
- §2.5 — insert — ambiguity — epoch sweeps the four families in the listed order (checkpoints before lapse etc.) — implementation/routes/checkpoints.py:54-107
- §2.5 — revise — mismatch — lapse trigger "has passed" → "has been reached" (impl lapses at `clock >= expires_at`) — implementation/routes/checkpoints.py:84
- §2.9 — revise — mismatch — path identifiers resolve immediately after role authorization and before body examination; only body-carried FKs wait for well-formedness — e.g. implementation/routes/reviews.py:154-160, implementation/routes/applications.py:196-199
- §2.10 — revise — mismatch — reordered the priority ladder to impl's actual order (auth → role → path existence → body well-formedness → ownership → body-FK existence → state → OCC → compliance → temporal → cross-entity → capacity/fiscal), with a clause that §3 endpoint narratives govern finer relative order — all route files
- §3.1 — revise — mismatch — dropped "unique `code`" (impl enforces no code uniqueness) — implementation/routes/standards.py:45-59
- §3.1 — insert — ambiguity — review creation requires institution in APPLIED/UNDER_REVIEW/LAPSED/CERTIFIED; SUSPENDED or **DECERTIFIED** → `ERR_INVALID_STATE`, checked before OCC (the flagged known candidate) — implementation/routes/reviews.py:70-77
- §3.1 — insert — mismatch — scoring's DRAFT-state check precedes payload validation — implementation/routes/reviews.py:157-160
- §3.1 — insert — ambiguity — PASS/CONDITIONAL finalization also clears `current_review_id` — implementation/routes/reviews.py:220
- §3.1 — insert — ambiguity — reviews listable with filters `institution_id`, `standard_id`, `status` — implementation/routes/reviews.py:130-138
- §3.3 — revise — mismatch — registration recomputes `pipeline_stage` per §3.4 (can land in `DOCS_READY`) and computes `docs_complete` from initial documents, instead of always landing in `REGISTERED` — implementation/routes/participants.py:54-56
- §3.3 — insert — ambiguity — navigator-intake `agency_user_id` records the caller's `X-User-ID` even when the caller is a CoalitionAdmin — implementation/routes/referrals.py:54
- §3.5 — insert — ambiguity — `capacity` validated only as an integer; non-positive values accepted (event simply unbookable) — implementation/routes/events.py:42
- §3.5 — insert — ambiguity — `alt_id_accepted=true` violation pinned as `ERR_VALIDATION`, evaluated after the institution-certified check — implementation/routes/events.py:77-80
- §3.5 — revise — mismatch — event roster retrievable by any institution officer (no ownership restriction), not just the hosting officer — implementation/routes/events.py:120-121
- §3.6 — revise — mismatch — application-create gate order rewritten to impl order: docs completeness → id_type among VERIFIED docs → referral linkage → institution CERTIFIED → standard alt-ID admissibility — implementation/routes/applications.py:100-127
- §3.6 — revise — mismatch — decision payload: `outcome` enum APPROVE/DECLINE, `decline_reason` required on DECLINE (was "optional"), officer-ownership check pinned before state check — implementation/routes/applications.py:199-215
- §3.6 — insert — ambiguity — approval gates explicitly evaluated in narrative order (certified → barrier → education) — implementation/routes/applications.py:220-242
- §3.6 — insert — ambiguity — `account_number` format pinned as `acct_` + 12 hex chars — implementation/routes/applications.py:246
- §3.6 — insert — ambiguity — BarrierCase created with `resolution_note` null; every decline records `decided_by_user_id` — implementation/routes/applications.py:271, 258
- §3.6 — insert — ambiguity — escalation may attach an optional `resolution_note` — implementation/routes/barrier_cases.py:131
- §3.6 — revise — mismatch — report-closure check order: ownership → OPENED state → `closed_at` comparison (validation after state) — implementation/routes/applications.py:297-304
- §3.7 — insert — ambiguity — checkpoint on an application CLOSED_EARLY with `closed_at` after `due_date` matches no rule and stays PENDING — implementation/routes/checkpoints.py:64-72
- §3.9 — insert — ambiguity — `program_year` is an integer — implementation/routes/grants.py:23
- §3.9 — insert — ambiguity — no grant-status or institution-certification gate at report draft time — implementation/routes/reports.py:40-51
- §3.9 — insert — ambiguity — report review `outcome` enum pinned as APPROVE/REJECT — implementation/routes/reports.py:141

**Key findings**: the known candidate was confirmed and pinned (reviews.py:70-73 rejects review creation on SUSPENDED or DECERTIFIED institutions with ERR_INVALID_STATE, before the OCC check). The largest revisions were §2.9/§2.10: the implementation uniformly resolves path-identifier existence before body well-formedness and applies ownership after resource loading, contradicting the original global ordering; the ladder was rewritten to match, with §3 narratives carrying endpoint-specific gate order where the impl deviates from tier defaults (application create, approve). Also notable: participant registration can land in DOCS_READY (not always REGISTERED), review finalization on PASS/CONDITIONAL clears `current_review_id`, and AccountStandard `code` uniqueness is not enforced.
