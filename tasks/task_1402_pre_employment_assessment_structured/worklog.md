# Worklog — task_1402_pre_employment_assessment_structured

## Step 1: Create Task Directory — 2026-08-13T03:46:00.000Z

Task directory `tasks/task_1402_pre_employment_assessment_structured/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T05:23:00.000Z

## Deliverables (all three written, lint-clean)

- `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/SCAFFOLD.yaml` (§1.0–§1.7, 1264 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design:` key, 1343 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design:` key, 2082 lines)

## Scaffold shape (harder-than-expert calibration)

- **17 entities, 81 endpoints, 61 error codes, 7 roles** — compliance_audit primary archetype + multi_party_negotiation secondary; graph topology (self-referential guide revision chain, many-to-many calibration); posture-driven gating (AssessmentCycle posture gates every child op); segregation_of_duties role model.
- **State machines**: cyclic instrument validation loop (VALIDATED→EXPIRED→REVALIDATION→VALIDATED, clock-materialized), branching freeze/unfreeze cycle restoring `frozen_from_posture`, parallel `admin_status × feedback_status` dimensions on CandidateAssessment, supersede-driven guide retirement, SCORED↔COMPLETED session revert on scorecard void.
- **Calculations**: four-fifths adverse-impact rule with pinned round-rate-then-divide-then-round order (0.4999 vs 0.5000 divergence proven), strict `< 0.8000` flag boundary, MIN_GROUP_N/NO_SELECTIONS/UNDISCLOSED conventions; weighted composite with renormalization + clamp; pinned-order quorum gate where voiding shrinks `submitted` but not `required`; RAW vs LENIENCY_ADJUSTED calibration variants (0.6875 vs 0.6768 on identical data); retention expiry with inclusive-feedback / strict-purge asymmetry; two compensating ledgers (interviewer minutes, vendor content copies).
- **Concurrency**: two true-race OCC rules (cycle PATCH `expected_cycle_version`, guide supersede `expected_superseded_guide_version`), 412s, no forbidden vocabulary.

## Test designs

- **§1.8: 24 instances across all 9 rules** (each rule ≥2; differentiation clauses honored — dual variants on different entity domains, combinatorial modes a/b/c all present, three distinct validation-priority category pairs, three distinct interval semantics, two conserved quantities). All formula-derived asserts are pre-computed literals (verified with Python: 0.7413/0.6933/0.6000/0.7293/0.7173 composites, 0.8000/0.4999 ratios, 2028-08-14T12:00:00Z retention expiry, etc.).
- **§1.9: 67 active corner instances + 11 excluded_because stubs** across all nine claim-guide sections, including RBAC ownership matrix (HM/Interviewer/Candidate/VendorRep), SoD positives+negatives, OCC stale-version pairs, envelope/pagination, conditional monitor flag, version-pinning vs retired-guide usability.

## Verification results

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs
have reverse-reachability in §1.5.  (81 endpoints, 17 entities, 24+67 instances, 2077 calls scanned)
```

Plus self-run checks: zero forbidden race vocabulary, zero unbound `${var}` placeholders, every `grounds:` reference resolves, every catalog error referenced and vice versa, instance names unique across both files. Two design gaps found and fixed during replay: `ERR_GUIDE_PINNED` was unreachable (added APPROVED→RETIRED direct-retire path gated on `pinned_cycle_count == 0`) and `ERR_ADVERSE_IMPACT_UNRESOLVED` was unreachable (added `freeze_reason` input to the freeze endpoint allowing manual ADVERSE_IMPACT holds).

## Step 3: Copy Shared Files — 2026-08-13T05:24:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1402_pre_employment_assessment_structured/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T05:47:00.000Z

The PRD is complete and all checks pass. Final document: `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/workspace/PRD.md` (416 lines).

**What was generated:** A prose PRD for the Pre-Employment Assessment & Structured Interview API, derived solely from `SCAFFOLD.yaml` (the difficulty/corner design files were not opened). Structure: §1 Introduction (3 paragraphs from the scenario); §2.1–2.10 covering RBAC with per-role identity semantics, the verbatim response-envelope contract, pagination, resource identity/versioning (including the two append-only entities `ContentLedgerEvent`/`RetentionPurgeEvent` that carry only `id` + `created_at`), the logical clock (startup default 2026-08-01T00:00:00Z, strict-inequality materializations), OCC, precision (4dp round-half-up with pinned rounding orders), the 17-tier validation priority ordering, nested-resource resolution, and ownership/SoD; §3.1–3.9 as the scattering zone organized by domain lifecycle (vendors/ledger → instruments/evidence → guides/rubric chain → requisitions/cycles → candidates/accommodations → sessions/scorecards/calibration → adverse impact → composite/decisions/feedback → retention/purge); §4 endpoint table (81 rows, 4 columns); §5 error catalogue (61 rows, 2 columns).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + query params + common fields + sub-structure names: 131 required, 131 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 17-tier global ordering expressed in §2.8 plus endpoint-specific orderings for the five densest endpoints (cycle activate, session create, decision create, feedback, accommodation approve), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (PATCH /talent/cycles/{id} + expected_cycle_version + ERR_STALE_CYCLE_VERSION/412; POST /talent/interview-guides/{id}/revisions + expected_superseded_guide_version + ERR_STALE_GUIDE_VERSION/412), no race framing, 0 missing
- state_machines[].transitions: 45 checked (all 12 machines incl. vendor depth-3 cascade, cycle close 3-link chain, scorecard void compensation, asymmetric reinstatement), 45 fully expressed, 0 missing
- calculations[]: 7 checked (adverse_impact_ratio with pinned round-then-divide order, candidate_composite_score with renormalization and 0.6/0.4 weights, decision_quorum_gate with pinned evaluation order, interviewer_calibration_index RAW vs LENIENCY_ADJUSTED, retention_expiry inclusive-feedback/strict-purge gates, interviewer_committed_minutes conserved ledger, vendor_content_ledger non-negative invariant), 7 fully expressed, 0 missing
- validations[] conditions: 61 error IDs all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all 81 endpoints' side effects expressed; multi-endpoint applies_to scopes (ERR_VENDOR_NOT_ACTIVE ×7, ERR_ASSESSMENT_NOT_COMPLETED ×3, ERR_GUIDE_NOT_APPROVED ×4, ERR_OUTSIDE_ADMINISTRATION_WINDOW ×4, ERR_DECISION_ALREADY_FINALIZED ×2) enumerated, 0 missing
- entities[].fields[] structured content: defaults (TIER_2, RAW, 730 days, 8/day, monitor=true, zero counters), nullability (validity_expires_at, terminated_at, closed_at, frozen fields, scheduled_for), and immutability (vendor_id, evidence, snapshots) reconstructible from prose, 0 missing
- sibling-branch symmetry: 10 groups checked (terminate ×2, retire ×4 instruments, retire ×3 guides, freeze ×3, unfreeze ×3, close ×5, cancel ×4, PROVISIONAL/FINAL, RAW/LENIENCY_ADJUSTED, approve-state branches), 10 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 744
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional verifications:** §2.2 is byte-identical to the canonical `section-2.2-response-structure.md`; §4 table matches scaffold endpoints exactly (method, path, authorized roles — 81/81); §5 table matches scaffold error catalog exactly (id, HTTP status — 61/61); zero operator-syntax leakage (`==`, `>=`, `+=`, `->` etc.) outside backticks; no fuzzy quantitative wording; PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-13T06:25:00.000Z

Done. Generated the complete test infrastructure for task_1402.

## What was produced

**`test_helpers/`** (9 modules, all importing cleanly):
- `types.py` — all 16 entities as TypedDicts plus status/role enums; the two append-only entities (`ContentLedgerEvent`, `RetentionPurgeEvent`) carry only `id` + `created_at` per PRD §2.4.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per §4 endpoint (all ~50 routes, `/talent` prefix).
- `api_errors.py` — full 61-entry `ApiErrorId` enum + HTTP status map, registered with the framework via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` plus `get_group_breakdown` snapshot helper.
- `factories.py` — input-only payload factories with monotonic unique `external_ref`/instrument codes.
- `constants.py` — thresholds (0.8000 four-fifths, MIN_GROUP_N 2, 0.7000/0.5000 calibration, quorum 2/3, 72h window, 15..240 min, 730d retention, canonical rubric/window).
- `test_users.py` — shared opaque-role headers plus mandatory per-instance builders for the three entity-backed roles (Interviewer, Candidate, VendorRepresentative).
- `fixtures.py` — composite builders: `create_validated_instrument`, `create_approved_guide` (SoD-safe two-admin), `setup_active_cycle`, `create_calibrated_interviewer`, `invite_and_complete_candidate`, `book_completed_session`, `submit_scorecard`, `setup_quorum_ready_candidate`, `setup_decided_candidate`, `setup_purged_assessment`, plus datetime helpers.

**`test_suite/`** — conftest.py + 15 numbered test files, **118 tests, all collected by pytest**:
- Queue A (difficulty): all 24 instances × ≥2 tests = 52 tests.
- Queue B (corner): all 67 non-stub instances × ≥1 test = 66 tests. The 11 `excluded_because:` stubs were not translated; their `difficulty_instance` cross-references all resolve.

## Verification results

- **Tag audit**: 118/118 tests carry exactly one `Design:` line; every tag resolves to a real instance in the source yaml; zero difficulty instances under 2 tests; zero corner instances missing.
- **PRD verbatim audit**: every quoted citation in every docstring survives a whitespace-normalized literal grep of `workspace/PRD.md` (31 spliced/ellipsized citations were rewritten to full-sentence quotes to pass C1/C3).
- **No `pytest.mark.skip`/`skipif`/`xfail`** anywhere; no scaffold references in generated code.
- One design-instance assertion was deliberately not translated: in `cycle_close_cancel_fanout_is_chained`, whether the close cascade cancels a SCHEDULED session of a *terminal* (COMPLETED) assessment is not uniquely derivable from PRD §3.4's wording ("each such cancellation ... cancels that candidate's still-SCHEDULED interview sessions"), so the test asserts only the uniquely-derived outcomes (assessment cancellation, count decrement, retention re-anchor) and leaves that gap as a gap.

Key paths:
- `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/test_suite/`

## Step 6: Generate Implementation — 2026-08-13T06:25:00.000Z

Implementation complete. Summary of what was built and verified:

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/workspace/implementation/` — Python + Flask, in-memory only:

- **`start.sh`** — guarded pip install (`if ! python3 -c "import flask"`), then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground, cold-boot HTTP-ready in ~1s.
- **`app.py`** — blueprint registration + envelope-correct error handlers (404/405 map to `ERR_NOT_FOUND`).
- **`db.py`** — dict-of-dicts store, empty at boot, logical clock initialized to `2026-08-01T00:00:00Z`; no seeding anywhere.
- **`errors.py` / `response.py` / `middleware.py` / `util.py` / `serializers.py`** — full error catalog (61 IDs with exact HTTP codes), the `meta/response_type/data` envelope with `limit/offset/total_count/has_more` pagination, `X-User-ID`/`X-User-Role` auth with entity-backed role resolution (Interviewer/Candidate/VendorRepresentative → 401 if the backing entity doesn't exist).
- **`routes/`** — 13 blueprints covering all 60+ endpoints: vendors (+content ledger, depth-3 suspend cascade, asymmetric reinstate), instruments (+evidence, cyclic validation lifecycle), guides (rubric checks, OCC-guarded supersede chain, SoD approve), requisitions, cycles (posture machine, OCC PATCH, freeze/unfreeze gates, close cascade), candidates (withdraw cascade), assessments (schedule/start/complete/no-show/cancel/reschedule/feedback), accommodations, interviewers + calibrations, sessions (double-booking half-open intervals, daily capacity, window fit, guide pin), scorecards (submit/void with weighted_total + session SCORED↔COMPLETED compensation), decisions (quorum gate `max(2, min(3, sessions))`, SoD, FILLED/DECIDED auto-transitions), adverse-impact snapshots (pinned round-rate-then-divide order, exactly-0.8000-not-flagged, flagged-FINAL freeze), retention sweeps (strict-expiry purge, scorecard redaction, purge events), and the logical-clock endpoint (strict->365d lapse, strict->expiry instrument expiry).
- **`services/core.py`** — composite score (renormalized partial coverage, clamped assessment component, 0.6/0.4 blend), calibration index (RAW + LENIENCY_ADJUSTED variants, lapse below 0.5000), retention anchoring, shared cancel cascade, computed counters.

Key fidelity decisions: PRD prose wins over scaffold ordering (cycle create/activate readiness gates run instrument→vendor→guide per PRD §3.4); validation tier order enforced for dual failures (window before raw-score, expired-evidence before missing-evidence, SoD before duplicate before quorum before rationale, etc.); OCC limited to exactly the two declared endpoints.

## Verification

Three smoke suites run against fresh boots — 108 + 141 + 244 checks, all passing — covering every entity lifecycle, both OCC 412 paths, all cascades, boundary conditions (0.7000 practice score, 72h window inclusive, exactly-365-day calibration lapse, exactly-0.8000 impact ratio, closed window endpoints), pagination envelope, and entity-backed auth. Confirmed fresh-process boot per invocation with empty state each time.

## Step 7: Run Tests and Iterate — 2026-08-13T07:05:00.000Z

The diagnostic loop is complete — all 8 parallel rounds pass 118/118.

**Summary**

- **Iterations run:** 2 full 8-round parallel sweeps (plus 1 single-round validation between them).
  - Sweep 1: 108–109/118 per round; failure union = 11 tests (9 deterministic across all 8 rounds, 2 flaky).
  - Sweep 2 (post-fix): **118/118 in every round — clean.**

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `assertions.py` — added `assert_iso_instant_equal(actual, expected)`: instant-level datetime comparison. The failing tests asserted exact-string equality on `validity_expires_at` / `closed_at` / `retention_expires_at` / `retention_expires_at_snapshot`, but PRD §2.4 pins the three-fractional-digit rendering only for `created_at`/`updated_at` (§2.2 for `api_request_timestamp`); the string form of other datetime fields is PRD-silent, while the instant value is PRD-pinned. STEP 1c coverage correction — the covered assertion (the instant) kept, the uncovered one (string form) removed.

- **Fixes applied to `test_suite/`:**
  - `test_04_state_machine_cycles_and_parallel_dimensions.py` — `_build_instrument_cycle_setup`: setup CRITERION evidence now expires 2026-09-01 (was 2027-08-01) so it is no longer current at revalidation time; the revalidation test's asserted `validity_expires_at` (2027-12-01) is then arithmetically correct per PRD §3.2's min rule (previously the still-current original CRITERION made 2027-08-01 the PRD-correct answer). Three assertions switched to `assert_iso_instant_equal`.
  - `test_05_cascades.py` — `closed_at` and `retention_expires_at` assertions → instant comparison.
  - `test_13_calculation_corners.py` — `validity_expires_at` assertion → instant comparison.
  - `test_08_cross_entity_gates.py` — fixture created a cycle pinning a PILOT guide, which PRD §3.4's creation gate makes unconstructible (create fails with `ERR_GUIDE_NOT_APPROVED` during setup). g2 is now APPROVED at creation; the test retires it via the only PRD-reachable path (supersede-approval, §3.3 "retires a guide regardless of pins"), then asserts activate → `ERR_GUIDE_NOT_APPROVED`.
  - `test_15_endpoints_rbac_and_crosscutting.py` — `test_candidate_withdraw_cascade` asserted `WITHDRAWN` for a PENDING accommodation on a COMPLETED (terminal) assessment, contradicting PRD §3.5's "every PENDING accommodation request on *those* assessments" (the cancelled set). Now asserts the terminal assessment's request survives as PENDING, and adds a second-cycle INVITED assessment whose PENDING request *is* cascade-withdrawn — keeping link-3 coverage PRD-faithful.

- **Fixes applied to `implementation/`:**
  - `serializers.py` `_base` — added `retention_expires_at_snapshot` to the datetime field list; it was rendering as RFC 1123 (`Mon, 14 Aug 2028 12:00:00 GMT`) instead of ISO 8601, breaking the purge event's audit-copy contract (PRD §3.9). Genuine implementation bug surfaced by the format-cluster investigation.

- **Flaky failures (sweep 1 only, did not recur in sweep 2):** `test_feedback_already_sent_rejected` (5/8 rounds, "API server could not be restarted" — runner's fixed 15s per-test restart poll exhausted) and `test_feedback_after_retention_expired_rejected` (1/8, ConnectionError). Root cause: host-level contention — several other benchmark pipeline sessions run concurrent sweeps on this machine, and my 8 lockstep rounds land at the same progress offset when a transient stall hits. No code change made for these; the confirming sweep was clean.

- **Feedback for generators:** (1) unit-test-generator emitted exact-string datetime assertions on fields whose rendering PRD §2.4 leaves unpinned — a DEFAULT-VALUE/COMPUTED-FIELD-silence-adjacent miss (rendering silence); (2) the revalidation test's arithmetic forgot the original CRITERION stays current (fixture/test arithmetic bug); (3) the guide-gate test built a PRD-impossible precondition (PILOT guide pinned to a cycle) — a fixture-vs-PRD inconsistency; (4) the withdraw-cascade test mis-scoped "those assessments" to include a terminal assessment.

## Step 8: Finalize PRD — 2026-08-13T07:20:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/workspace/PRD_FINALIZED.md` is written with exactly one inline insertion.

## Size delta

- Lines: 416 → 416 (0%; the insertion extends the existing §2.4 paragraph, no new lines/sections)
- Chars: 78,063 → 78,822 (+0.97%); words: 10,456 → 10,539 (+0.79%)

## Change log

- **§2.4 — insert** — extended the timestamp paragraph to pin that the ISO 8601 UTC / three-fractional-digit / null-when-unset rendering applies to every other datetime-valued resource/audit-event field, naming all 21: `terminated_at`, `validity_expires_at`, `filed_at`, `effective_from`, `effective_until`, `closed_at`, `scheduled_for`, `started_at`, `completed_at`, `retention_expires_at`, `purged_at`, `decided_at`, `trained_at`, `certified_at`, `scheduled_start`, `scheduled_end`, `submitted_at`, `voided_at`, `finalized_at`, `computed_at`, `retention_expires_at_snapshot`; with `administration_window_start`/`administration_window_end` explicitly pinned as the two exceptions rendered in RFC 1123 HTTP-date form — `implementation/serializers.py:13-19`, `implementation/util.py:23-30` (`fmt_dt`), and Flask-default RFC 1123 rendering of the two window fields verified live against a booted server (`"Mon, 10 Aug 2026 00:00:00 GMT"`).

## Step-7 items requiring no edit (verified impl already matches PRD verbatim)

- **test_04 fixture (evidence expiry 2027-08-01 → 2026-09-01)** — pure fixture bug; PRD §3.2's earliest-`effective_until`-of-current-CRITERION+CONTENT rule is exactly `instruments.py:173-175`.
- **test_08 fixture (PILOT guide at cycle creation)** — pure fixture bug; PRD §3.4's `ERR_GUIDE_NOT_APPROVED` creation gate is exactly `requisitions.py:119-120`.
- **test_15 withdraw cascade** — test contradicted PRD; §3.5's "every PENDING accommodation request on *those* assessments" (the cancelled set) matches `core.py:332-358` + `candidates.py:77-79` (COMPLETED assessment's PENDING request survives; cancelled INVITED assessment's request withdrawn).

## Pre-edit search log (mandatory per-edit)

**Edit 1 (the only edit):**
- (a) **Subject:** wire string rendering of datetime-valued response fields (the step_7 cluster: `assert_iso_instant_equal` addition; `validity_expires_at`/`closed_at`/`retention_expires_at`/`retention_expires_at_snapshot` assertions in test_04/05/13; `serializers.py` `_base` fix adding `retention_expires_at_snapshot`).
- (b) **Impl paths enumerated:** `serializers.py` `_base` datetime list (all 17 resource serializers route through it — 87 serializer-mediated responses confirmed by grep; the only raw responses are `retention.py:66,80` summary objects, whose `now` uses `fmt_dt`); `util.py:23-30` `fmt_dt` (ISO 8601, ms-truncated, `Z`, null→null); every datetime field source — all 11 `parse_dt` callsites and all `db.get_now()`/`now` assignments across `routes/{instruments,requisitions,cycles,candidates,assessments,accommodations,interviewers,sessions,scorecards,decisions,snapshots,retention,vendors}.py` — yielding exactly 23 datetime field names, all in the serializer list except `administration_window_start`/`end`; `response.py:16-19` `api_request_timestamp` (already pinned by §2.2, untouched); live boot probe confirming `validity_expires_at` renders `2027-01-01T00:00:00.000Z` while cycle windows render `Thu, 10 Sep 2026 00:00:00 GMT`.
- (c) **Wording adjustment:** the draft began as a universal claim ("every other datetime-valued field renders ISO 8601 with three fractional digits"); the enumeration proved that false at the two cycle window fields (RFC 1123 via Flask's default JSON provider, verified live). The committed wording therefore lists the 21 ISO-rendered fields exhaustively and pins the two window fields' RFC 1123 form as named exceptions — no universal quantifier left unqualified. The null clause is scoped to the ISO-rendered fields (window fields are required at creation, `requisitions.py:122-123`, so never null). The clock endpoint's `now` field was deliberately left unclaimed (summary field, not resource-carried; outside step_7 scope).

No tests were run as part of this step beyond the live probe; the edit is prose-only and consistent with the post-sweep 118/118 implementation.

## Step 9: Complete PRD — 2026-08-13T07:40:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1402_pre_employment_assessment_structured/workspace/PRD_COMPLETED.md`.

**Size**: PRD_FINALIZED.md 416 lines / 79,183 chars → PRD_COMPLETED.md 416 lines / 81,573 chars (+2,390 chars, +0 lines — all edits are inline in existing paragraphs; no sections added).

**Counts**: 20 changes total — 19 ambiguity-pins, 1 mismatch-revision.

**Changes** (section — insert|revise — class — what — impl ref):

- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out-of-range, negative) → `ERR_INVALID_REQUEST`; list ties on `created_at` broken by creation order — `implementation/util.py:118-136, 149-151`
- §2.4 — insert — ambiguity — creations set `version` to 1 — `implementation/routes/vendors.py:45` (all create paths)
- §2.6 (cycle OCC) — insert — ambiguity — omitted/non-integer `expected_cycle_version` → `ERR_INVALID_REQUEST` — `implementation/routes/cycles.py:99-101`
- §2.6 (guide OCC) — insert — ambiguity — omitted/non-integer `expected_superseded_guide_version` → `ERR_INVALID_REQUEST` — `implementation/routes/guides.py:114-116`
- §2.8 — revise — mismatch — added refinement: field-level shape failures (tier 16) are raised at the point the endpoint first reads the field and may precede higher-tier checks not depending on that field (impl validates required/shape fields inline before some higher-tier gates, e.g. cycle-create window/capacity parsing before the window-order check, candidate field parsing before the duplicate-ref check) — `implementation/routes/requisitions.py:121-131`, `implementation/routes/candidates.py:24-30`
- §3.1 — insert — ambiguity — `VendorRepresentative` attempting `DISTRIBUTE` → `ERR_FORBIDDEN` — `implementation/routes/vendors.py:103-105`
- §3.1 — insert — ambiguity — suspend from non-`ACTIVE`, reinstate from non-`SUSPENDED`, terminate from neither → `ERR_INVALID_STATE` — `implementation/routes/vendors.py:140-143, 182-183, 211-212`
- §3.2 — insert — ambiguity — `pass_floor` not strictly below `max_score` → `ERR_INVALID_REQUEST` — `implementation/routes/instruments.py:50-51`
- §3.2 — insert — ambiguity — evidence filing admitted regardless of `validation_status` — `implementation/routes/instruments.py:223-255` (no state gate)
- §3.3 — insert — ambiguity — duplicate `competency_code` / out-of-range `weight` / `scale_max` → `ERR_INVALID_REQUEST` — `implementation/routes/guides.py:42-55`
- §3.3 — revise — ambiguity — weight-sum check quantizes the summed total to 4dp with round-half-even (Decimal `quantize` default) before comparing to 1.0000 — `implementation/routes/guides.py:61-64, 68-72`
- §3.3 — insert — ambiguity — revision payload's omitted `scoring_mode` defaults to `RAW` — `implementation/routes/guides.py:125`
- §3.4 — insert — ambiguity — `HiringManager` may read only own requisitions (`ERR_OWNERSHIP_MISMATCH`) — `implementation/routes/requisitions.py:62-63`
- §3.4 — insert — ambiguity — duplicate-invitation check counts any prior assessment for the (cycle, candidate) pair regardless of `admin_status`, so re-invite after cancellation/purge is refused — `implementation/routes/cycles.py:298-301`
- §3.5 — insert — ambiguity — `Candidate` may read only own candidate record — `implementation/routes/candidates.py:56-57`
- §3.5 — insert — ambiguity — `raw_score` accepts any JSON number (integer or float) — `implementation/routes/assessments.py:137-139`
- §3.5 — insert — ambiguity — marking no-show before `scheduled_for` → `ERR_INVALID_STATE` — `implementation/routes/assessments.py:162-164`
- §3.5 — insert — ambiguity — approval `decision_note` required but only non-empty (no minimum length, unlike denial's 10) — `implementation/routes/accommodations.py:66-68`
- §3.5 — insert — ambiguity — denial `decision_note` under 10 chars → `ERR_INVALID_REQUEST` — `implementation/routes/accommodations.py:93-95`
- §3.7 — insert — ambiguity — `UNDISCLOSED` breakdown entry carries null `selection_rate`/`impact_ratio` and is present only when undisclosed applicants exist; `group_breakdowns` ordered `GROUP_A`–`GROUP_D` then `UNDISCLOSED` — `implementation/routes/snapshots.py:74, 129-137`

Notable non-changes (verified already pinned or behaviorally equivalent): the RFC 1123 rendering exception for cycle window fields (impl relies on Flask's datetime JSON serialization, matching PRD §2.4); instrument validate's `ERR_EVIDENCE_EXPIRED`-before-`ERR_EVIDENCE_TYPE_MISSING` ordering (matches tier 11 before 13); the guide-approval weight-sum-vs-SoD check order (impl runs weight-sum first, contra tiers 9/10, but unobservable since a guide reaching approval always has a valid sum); terminate's `content_copies_outstanding != 0` vs PRD "above zero" (equivalent, balance can never go negative); freeze's accepted-but-unpersisted `reason_note` (PRD requires only that it be suppliable, not stored).

## Step 7: Diagnostic Iterate Loop — 2026-08-13T07:00:00.000Z

### Sweep 1 (8 parallel rounds): 108–109/118 per round; union of failures = 11 tests

Deterministic (8/8 rounds) — 9 tests in 4 clusters; flaky/environmental — 2 tests:

1. **Datetime string-format assertions (5 tests)** — tests asserted exact-string equality on
   non-`created_at`/`updated_at` datetime fields (`validity_expires_at`, `closed_at`,
   `retention_expires_at`, `retention_expires_at_snapshot`) while PRD §2.4 pins the
   three-fractional-digit rendering only for `created_at`/`updated_at` (§2.2 for
   `api_request_timestamp`). The instant value is PRD-pinned; the string form is not →
   STEP 1c split: added `assert_iso_instant_equal` (instant comparison) to
   `test_helpers/assertions.py` and used it in test_04 (×3), test_05 (×2), test_13 (×1).
2. **test_04 revalidation expected value wrong (1 test)** — the fixture's original CRITERION
   evidence (until 2027-08-01) was still *current* at revalidation time (2026-09-02), so the
   min-rule yields 2027-08-01, not the asserted 2027-12-01. Fixed the fixture
   (`_build_instrument_cycle_setup`): setup CRITERION now shares the 2026-09-01 expiry so the
   revalidation recompute provably uses only the fresh evidence; the asserted 2027-12-01 is
   then correct. Sibling tests re-derived: first-validation min stays 2026-09-01; expiry,
   revalidation-gate tests unaffected.
3. **test_08 guide-gate setup unreachable (2 tests)** — fixture created a cycle pinning a
   PILOT guide, which PRD §3.4's creation gate forbids (`ERR_GUIDE_NOT_APPROVED` at create).
   The only PRD-reachable path to a non-APPROVED pinned guide is supersede-approval
   ("retires a guide regardless of pins", §3.3). Fixture now creates cy2 with an APPROVED g2;
   the test retires g2 via supersede-approval, then asserts activate → ERR_GUIDE_NOT_APPROVED.
4. **test_15 withdraw-cascade accommodation scope (1 test)** — the test asserted WITHDRAWN
   for a PENDING accommodation on the COMPLETED (terminal) assessment, contradicting PRD
   §3.5's "every PENDING accommodation request on *those* assessments" (those = the cancelled
   INVITED/SCHEDULED/ACCOMMODATION_HOLD/IN_PROGRESS set). Fixed: ar1 on the terminal
   assessment now asserted to survive as PENDING; added a second-cycle INVITED assessment
   with a PENDING request that IS withdrawn by the cascade (keeps the cascade's link-3
   coverage, now PRD-faithful).
5. **Implementation bug found via (1)**: `retention_expires_at_snapshot` was missing from the
   serializer's datetime field list, so it rendered as RFC 1123
   ("Mon, 14 Aug 2028 12:00:00 GMT") instead of ISO 8601. Fixed `serializers.py` `_base`.

Flaky (not every round): `test_feedback_already_sent_rejected` (5/8 rounds, "API server could
not be restarted" at setup — the runner's fixed 15s per-test restart poll exhausted) and
`test_feedback_after_retention_expired_rejected` (1/8, ConnectionError mid-test). Host is
shared with several other concurrent benchmark pipelines (load avg >14); restart failures
cluster at the same progress point because the 8 rounds run in near-lockstep. Boot is ~1s
solo; will mitigate only if it recurs after the deterministic fixes.

### Sweep 2 (8 parallel rounds, after fixes): 118/118 in every round — CLEAN

All 8 rounds passed 118/118. The sweep-1 flaky restart failures did not recur
(confirmed environmental: shared-host contention vs the runner's fixed 15s per-test
restart poll; no code change was made for them). Exit criteria met.

Fix summary:
- test_helpers/assertions.py: added `assert_iso_instant_equal` (instant-level datetime
  comparison; PRD pins the 3-fractional-digit rendering only for created_at/updated_at).
- test_suite/test_04: fixture CRITERION expiry aligned to 2026-09-01 so the revalidation
  min-rule assertion (2027-12-01) is arithmetically correct; three assertions switched to
  instant comparison.
- test_suite/test_05: two assertions (closed_at, retention_expires_at) → instant comparison.
- test_suite/test_13: validity_expires_at assertion → instant comparison.
- test_suite/test_08: `_build_two_cycle_gate_setup` now pins an APPROVED g2 (cycle creation
  with a PILOT guide is PRD-impossible); the guide-gate test retires g2 via the PRD §3.3
  supersede-approval path, then asserts activate → ERR_GUIDE_NOT_APPROVED.
- test_suite/test_15: `test_candidate_withdraw_cascade` asserts the terminal assessment's
  PENDING accommodation survives (PRD §3.5 "those assessments" scope) and adds a
  second-cycle INVITED assessment whose PENDING request IS cascade-withdrawn.
- implementation/serializers.py: added `retention_expires_at_snapshot` to the datetime
  field list (was rendering as RFC 1123 — a genuine implementation bug).

No tests deleted. No assertion weakened (exact error_id checks preserved throughout;
datetime assertions moved from string equality to instant equality — a STEP 1c coverage
correction, since PRD §2.4 pins the 3-digit rendering only for created_at/updated_at).
