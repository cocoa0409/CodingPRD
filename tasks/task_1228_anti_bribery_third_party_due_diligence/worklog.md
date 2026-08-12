# Worklog — task_1228_anti_bribery_third_party_due_diligence

## Step 1: Create Task Directory — 2026-08-12T02:40:00.000Z

Pre-assigned output folder `tasks/task_1228_anti_bribery_third_party_due_diligence` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Directory verified present and empty.

## Step 2: Generate Scaffold — 2026-08-12T03:35:00.000Z

(First subagent attempt terminated early with zero files on disk; re-spawned and completed cleanly. Verbatim summary of the successful run:)

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/` and the lint verdict is clean.

## What was built

**Design intent (beyond-expert calibration):** primary archetype `compliance_audit` × secondary `workflow_orchestration`; flat FK topology; cyclic state machines; `segregation_of_duties` role model with 6 opaque roles (ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead). Layers: cascading side effects, dual-variant calculation, rate/threshold triggers, optimistic concurrency.

**SCAFFOLD.yaml** (~1500 lines): 14 entities (ThirdParty hub + ScreeningCheck, Questionnaire, RedFlag, EscalationCase, Contract, Certification, PaymentRequest, GiftHospitalityEntry, ReDiligenceCycle, AuditExercise, TrainingAssignment, CountryRiskProfile, RiskScoringPolicy), 12 state machines (cyclic questionnaire RETURNED→SUBMITTED loop; ThirdParty DD_REVIEW⇄ENHANCED_REVIEW and APPROVED⇄SUSPENDED loops), 3 OCC concurrency rules, 5 calculations with pinned rounding/evaluation order, 29-error catalog on a 10-level priority ladder, 60 endpoints including the `/_clock/set_current_utc` test-driving endpoint (default 2026-05-01T00:00:00Z).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 19 instances across all 9 rules, each with literal-computed asserts (e.g., provisional 73/HIGH vs final 100/CRITICAL divergence; per-entry rounding 3350+3350=6700 vs sum-then-round 6699; commission brackets 9.00/12.00/26.00 against blended cap 9.00 and hard cap 25.00; gift boundaries 24999 vs 25000 and window lower-bound exclusivity; audit half-open adjacency).

**SCAFFOLD_CORNER_DESIGN.yaml**: 48 active instances + 7 excluded-because stubs across all 9 claim-extraction sections (entities 7, state_machines 11, calculations 6, validations 13, rbac 6 including two SoD pair tests, cross-cutting 4 with three OCC 412 tests, consistency 1).

**Issues found and fixed during self-audit:** YAML flow-sequence quoting for `field?` markers and bracketed grounds refs; removed unreachable `ERR_ESCALATION_OPEN` (an open case always implies an escalated flag); made questionnaire issue legal from SCREENING so `ERR_SCREENING_UNRESOLVED` is reachable at accept; pinned ERR_ALREADY_TERMINAL precedence within priority 5; moved `enhanced_review_evidence` to payment-create payloads; renamed sub-resource path placeholders to `{id}` for lint FK reverse-reachability.

Final lint verdict block (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  954

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directories were inspected; the design was generated purely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-12T03:36:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1228_anti_bribery_third_party_due_diligence/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T03:55:00.000Z

PRD generation is complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/workspace/PRD.md` (295 lines).

**Structure:** §1 introduction (2 paragraphs, FCPA business context); §2 with 10 domain-derived subsections (RBAC, verbatim response envelope, pagination, resource identity/nested retrieval, logical clock & sweep, precision/rounding, OCC, segregation of duties, validation priority order, state machines & terminal lockdown); §3 with 9 subsections organized by business lifecycle (risk configuration → registration/provisional scoring → screening cascade → questionnaire/final scoring → escalation & party lifecycle → contracts/clauses/certifications → payments → gifts → re-diligence/audit/training); §4 endpoint table (60 endpoints, 4 columns); §5 error catalogue (29 errors, 2 columns).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 74 required, 74 present, 0 missing
- endpoints[].request_body/input: 27 required, 27 present, 0 missing
- path_params + common fields: 5 required, 5 present, 0 missing
(total required set: 106, 0 missing)
Status: PASS

Rule coverage check:
- validations[] priority ordering: expressed as a dedicated §2.9 tier-by-tier narrative (priorities 1–10, including the priority-5 ERR_ALREADY_TERMINAL-before-ERR_INVALID_STATE precedence and the clause-check-before-referential-gates note in §3.6), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed in §2.7 (questionnaire issue + third-party PATCH with expected_third_party_version, policy activate with expected_policy_version, all ERR_STALE_VERSION/412, rationale included, no race framing), 0 missing
- state_machines[].transitions: 12 machines, all from/to states, preconditions (with error ids), and side effects expressed in §3, including the 4-level HIT_CONFIRMED cascade, termination cascade, and escalation-decide outcome fan-out, 0 missing
- calculations[]: 5 checked, 5 expressed as precise prose (weighted provisional/final score with override and inclusive tier bounds; country-blended commission brackets with pinned evaluation order and 0.60/0.80/1.00 multipliers; gift rolling window with per-entry round-before-sum, half-open window, 25000-inclusive/50000-strict thresholds; re-diligence intervals 90/180/365/365 with REAFFIRM/DOWNGRADE/TERMINATE outcomes; 10-day inclusive audit notice with half-open overlap and adjacency allowance), 0 missing
- validations[] conditions: all 29 error ids matched to their trigger narratives in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: expressed in the workflow narratives (clock sweep quartet, screening auto-advance guard, snapshot pinning at approval, ledger compensation invariants, aggregate recompute on create/approve/void), 0 missing
- entities[].fields[] structured content: defaults (sanctioned=false, enhanced_review_evidence=false, ledger=0), null-until semantics (scores, valid_until, diligence_expires_at, decision fields), and enum memberships all reconstructible from prose
- sibling-branch symmetry: screening dispositions, escalation outcomes, re-diligence outcomes, and commission brackets each rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 565
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is content-identical to the fixed verbatim block; no fuzzy words or pseudocode operators anywhere; all state strings and enum values (including the industry/touchpoint score mappings and clause-code sets) appear verbatim.

## Step 5: Generate Unit Tests — 2026-08-12T04:30:00.000Z

Done. Generated the complete test infrastructure for task_1228.

## What was produced

**`test_helpers/` (Stage 1)** — `/home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/test_helpers/`
- `types.py` — 14 entity TypedDicts + 20 status/role enums (all entities carry `common_fields: true`)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 59 PRD §4 endpoints
- `api_errors.py` — 29 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (tier intervals, gift caps, multiplier bands, clause sets)
- `test_users.py` — all six roles are `identity: opaque`, so shared constants plus per-user builders (`sponsor_headers("u_sp9")` etc.) for the ownership/SoD scenarios
- `fixtures.py` — composite walkers: `setup_risk_basis`, `setup_third_party_in_state` (DRAFT→SCREENING→DD_REVIEW→APPROVED), `setup_active_contract`, `setup_approved_with_active_contract`, `setup_escalated_case`, `setup_audit_in_fieldwork`, gift/payment helpers; all setup via `get_success_data` with "Setup failed" diagnostics

**`test_suite/` (Stage 2)** — 11 files, **85 tests**, all collected cleanly by pytest:
- `test_01` registration/listing (7) · `test_02` risk scoring (8) · `test_03` screening/escalation (11) · `test_04` questionnaire (4) · `test_05` third-party lifecycle incl. termination cascade (7) · `test_06` contracts/certifications (6) · `test_07` payments (14) · `test_08` gifts (12) · `test_09` re-diligence (4) · `test_10` audit (6) · `test_11` security/OCC (6)

**Coverage audit (machine-checked):** all 19 difficulty instances have ≥2 tests tagged `Design: Difficulty/...`; all 47 translatable corner instances have ≥1 test tagged `Design: Corner/...`; every tag is the docstring's last line and resolves to a real YAML instance; all 7 `excluded_because` stubs were skipped and their difficulty cross-references verified to resolve. All 135 citation spans ≥6 words match PRD.md verbatim (whitespace-normalized). No skip/xfail markers; no scaffold references in comments.

## Judgment calls to be aware of

1. **One instance intentionally skipped**: `Corner/state_machines/questionnaire_accept_with_queued_screening_rejected` expects `ERR_SCREENING_UNRESOLVED` for an accept attempted while the third party is still in SCREENING with QUEUED checks. But PRD §2.9 places `ERR_INVALID_STATE` at tier 5 and `ERR_SCREENING_UNRESOLVED` at tier 9, and §3.4 makes "party not in DD_REVIEW/ENHANCED_REVIEW" an `ERR_INVALID_STATE` failure — so a PRD-faithful implementation returns `ERR_INVALID_STATE` in this exact scenario. The asserted outcome is not uniquely derivable (arguably contradicts the PRD), so the gap stays a gap. The error itself remains reachable via ENHANCED_REVIEW with non-terminal checks, but no design instance covers that path, and freelance tests are forbidden.

2. **One pre-computed literal corrected**: difficulty instance `questionnaire_return_resubmit_cycle` asserts `fin == 16 (16 + 10 + 0)` — internally contradictory (16+10=26). The PRD formula (provisional 16 + questionnaire modifier 10) uniquely derives **26**, so the test asserts 26 / LOW rather than the YAML's typo.

3. `policy_activate_stale_version_returns_412` asserts `version == observed + 1` instead of the literal `2`, since the PRD pins "increments by one" but never pins the initial version value.

## Step 6: Generate Implementation — 2026-08-12T04:31:00.000Z

Done. The complete Python + Flask implementation is in `/home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/workspace/implementation/`.

**What was built**

- `start.sh` — executable launcher; guards the pip install behind `python3 -c "import flask"` (so per-test reboots skip it), then `exec python3 app.py` in the foreground on `0.0.0.0:$PORT` (default 10000).
- `app.py` — Flask entry point registering four blueprints, with `ApiError` → envelope error handler.
- `db.py` — in-memory store, **starts completely empty** (no seeding); logical clock defaults to exactly `2026-05-01T00:00:00Z`.
- `errors.py` — all 30 error IDs from SCAFFOLD §1.6 with their HTTP statuses.
- `response.py` — the exact envelope: `meta.api_request_id` (`req_...`), `meta.api_request_timestamp` (ISO-8601 with 3 fractional digits), `response_type` (`object`/`array`/`error`), `data`; list responses add `limit`/`offset`/`total_count`/`has_more` in `meta`.
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`), role-list RBAC (403 `ERR_UNAUTHORIZED_ROLE`), pagination parsing (limit default 10, 1–100; offset default 0).
- `services/core.py` — all five calculations (provisional/final risk scoring with round-half-up and the sanctions override evaluated after arithmetic; country-blended commission brackets with pinned evaluation order; per-entry-round-then-sum gift rolling window; re-diligence scheduling; 10-day audit notice with half-open overlap), the red-flag/escalation/termination cascades, and the deterministic clock sweep (cert lapse, cycle overdue + 30-day auto-suspend, training overdue, contract expiry — all strictly-greater on whole dates).
- `routes/` — all 59 endpoints across `config.py` (clock, country profiles, policies), `third_parties.py` (lifecycle, screening checks, questionnaires, red flags, escalation cases), `contracts.py` (contracts, certifications, payments), `operations.py` (gifts, re-diligence, audits, training).

**Verified by live smoke tests** (server rebooted fresh each time): full onboarding flow with correct provisional (70→HIGH) and final (85→CRITICAL) scoring; screening auto-advance; HIT_CONFIRMED cascades (PEP leaves provisional untouched, SANCTIONS forces 100/CRITICAL + auto-escalation + ENHANCED_REVIEW); escalation SoD and all three outcomes; OCC `ERR_STALE_VERSION` on PATCH/questionnaire/policy-activate; questionnaire supersede and RETURNED→SUBMITTED loop; clause-set gating by `approval_tier_snapshot`; commission brackets (13.00% vs effective cap 12.00% → `ERR_ENHANCED_REVIEW_REQUIRED`; 26.00% > 25.00% hard cap → `ERR_COMMISSION_CAP_EXCEEDED`; REIMBURSEMENT skips brackets); payment ledger approve/reverse with SoD both ways; gift per-entry FX rounding (333 × 0.005 → 2), rolling-window thresholds (≥25000 inclusive enhanced, >50000 strict hard cap), and aggregate repair on void; audit notice window (boundary-inclusive at +10d), half-open overlap (adjacency allowed), findings cascade, and close gating; re-diligence REAFFIRM/DOWNGRADE with correct successor due dates; clock-sweep overdue and 30-day auto-suspend; fresh-boot emptiness and the 2026-05-01 default clock.

One fidelity note: `gov_gift_rolling_12m_cents` is anchored at the latest APPROVED entry's event_date rather than the wall/logical "today", because PRD §3.8 explicitly requires the aggregate to include a just-approved entry whose event_date may be in the future.

**Orchestrator route-pair verification (pre-sweep):** implementation registers exactly the 60 (method, path) pairs SCAFFOLD.yaml §1.5 declares — 0 missing, 0 extra (subagent summaries said "59" because they counted the test-driving `/_clock/set_current_utc` separately; the normalized set match is exact).

## Step 7: Run Tests and Iterate — 2026-08-12T04:40:00.000Z

All 8 rounds pass: 85/85 across the board. (Orchestrator disk verification: results.1.json … results.8.json each report passed=85, failed=0, total=85, errors=0.)

## Summary

- **Iterations run:** 3 sweeps (initial + 2 fix-rerun cycles).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — `setup_third_party_in_state` had a duplicate-submit bug: when target was `DD_REVIEW` or `APPROVED`, it called `submit_third_party` directly and then again inside `advance_to_dd_review`, tripping `ERR_INVALID_STATE` on the second call. Inlined the "clear checks + assert DD_REVIEW" step instead of delegating to `advance_to_dd_review` after the initial submit.
- **Fixes applied to `test_suite/`:**
  - `test_suite/test_03_screening_and_escalation.py` — `test_escalation_decider_cannot_be_escalator` called the `officer_headers` pytest fixture as a function (`officer_headers()`), causing `TypeError: 'dict' object is not callable`. Removed the parens to use the dict fixture directly, consistent with the rest of the test.
- **Fixes applied to `implementation/`:**
  - `workspace/implementation/db.py` — added `logical_iso()` that renders the in-store logical clock as an ISO-8601 UTC string with 3 fractional digits; `now_iso()` retained for response-meta `api_request_timestamp`.
  - `workspace/implementation/services/common.py` — `stamp_new` and `touch` now use `dbmod.logical_iso()` so `created_at`/`updated_at` reflect the logical compliance clock per PRD §2.5 ("All date-sensitive behavior in the system reads from a logical clock, never from wall-clock time."). Previously they used wall-clock, so `created_at` was pinned to the run date rather than the 2026-05-01 startup default.

Final state: 8/8 rounds × 85/85 tests passing.

## Step 8: Finalize PRD — 2026-08-12T04:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1228_anti_bribery_third_party_due_diligence/workspace/PRD_FINALIZED.md` is written.

## Summary

**Line counts:** PRD.md 295 lines, PRD_FINALIZED.md 295 lines — 0% line delta (2 lines revised in place, no insertions/deletions of lines).

**Changes (2 edits, both tracing to the single Step 7 `implementation/` fix — the db.py/common.py logical-clock repair; the other two Step 7 items were pure test/fixture bugs where PRD already determines behavior):**

- §2.2 — revise — `api_request_timestamp` bullet now pins the envelope timestamp as wall-clock-at-response-time, explicitly not reading the §2.5 logical clock — `implementation/response.py:18`, `implementation/db.py:39-42` (`now_iso` = `datetime.now(timezone.utc)`).
- §2.4 — revise — `created_at`/`updated_at` sentence now pins both fields as stamped from the §2.5 logical compliance clock (never wall-clock), including the startup-instant consequence 2026-05-01T00:00:00Z — `implementation/services/common.py:14-23` (`stamp_new`/`touch` → `dbmod.logical_iso()`), `implementation/db.py:45-51`.

**Items requiring no edit:** the `test_helpers/fixtures.py` duplicate-submit fix (PRD §3.2 pins submit as DRAFT→SCREENING and §2.10 pins any non-permitted transition as `ERR_INVALID_STATE`; verified `routes/third_parties.py:196` enforces from-state `{"DRAFT"}`), and the `test_03` fixture-call fix (pure test bug).

**Per-edit pre-edit search log:**

1. **§2.4 edit (created_at/updated_at clock source)**
   - (a) Subject: which clock sources `created_at`/`updated_at` on domain records.
   - (b) Enumerated paths: `db.py:45-51` (`logical_iso` renders `DB["clock"]` with 3 fractional digits); `services/common.py:14-28` (`stamp_new`, `touch`, `bump`→`touch`); grep for all `stamp_new`/`touch`/`bump` call sites across `routes/config.py`, `routes/third_parties.py`, `routes/contracts.py`, `routes/operations.py`, `services/core.py` (cascades + sweep) — every record creation/mutation on all 14 entity types funnels through these two helpers; grep for direct `"created_at"`/`"updated_at"` assignments outside common.py found only serializers and `created_at`-ascending sort keys (`services/core.py:132-180`, `routes/third_parties.py:163,466`, `routes/operations.py:404,458`), so no non-logical writer exists; confirmed the wording is scoped to the two record fields and says nothing about `current_utc` (`routes/config.py:60`) or list ordering (§2.3 unchanged).
   - (c) Adjustment: wording kept strictly scoped to the two named fields ("both stamped from the logical compliance clock of §2.5"); no universal claim about all timestamps, so the envelope field and clock-set response remain correctly untouched by the sentence.
2. **§2.2 edit (api_request_timestamp clock source)**
   - (a) Subject: which clock sources the response-envelope `api_request_timestamp`.
   - (b) Enumerated paths: `response.py:15-19` (`_meta_base` is the sole writer, feeding `success_object`, `success_list`, and `error_response` — i.e., every 2xx and 4xx envelope); `db.py:39-42` (`now_iso` = wall clock, 3 fractional digits); grep confirmed no other writer. Cross-checked against §2.5's "never from wall-clock time" and the error-format bullet ("meta contains only api_request_id and api_request_timestamp") — both remain consistent.
   - (c) Adjustment: added the explicit carve-out "as a diagnostic envelope field it is not date-sensitive behavior" so the new sentence cannot be read as contradicting §2.5's blanket "never from wall-clock time," and covers both success and error envelopes since both share `_meta_base`.

## Step 9: Complete PRD — 2026-08-12T04:55:00.000Z

PRD_COMPLETED.md is complete. Final summary:

**Source vs output**: `workspace/PRD_FINALIZED.md` (295 lines) → `workspace/PRD_COMPLETED.md` (296 lines); char delta +4,398. Exactly one line added (a bullet in §2.2); every other change is an in-paragraph insert/revision. No new sections.

**Counts**: 17 ambiguity-pins, 5 mismatch-revisions.

**Ambiguity-pins (inserts)**:
- §2.2 — insert — ambiguity — undefined path or unsupported method answered in the error envelope with `ERR_NOT_FOUND` (404) — implementation/app.py:32-38
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; `total_count` is post-filter; `has_more` = `offset+limit < total_count`; `created_at` ties broken by creation order — implementation/middleware.py:45-67, response.py:36
- §2.4 — insert — ambiguity — `version` starts at 1; third-party `version` also increments on every `onboarding_status` change (auto-advance, escalation moves, sweep suspension, decision moves, re-diligence completion) but not on score-only recompute — implementation/services/common.py:14-28, services/core.py:289-295,317-325, routes/third_parties.py:563-580
- §2.4 — insert — ambiguity — `match_detail`/`return_note`/`conditions_note` persisted; all optional `reason` fields and the flag-disposition `note` accepted but never persisted or echoed — implementation/routes/third_parties.py:248-267 (reject/suspend read no body), contracts.py:236-243,325-333, routes/operations.py:188-209
- §2.5 — insert — ambiguity — clock-set response `current_utc` rendered ISO 8601 UTC with three fractional digits — implementation/routes/config.py:60
- §2.6 — insert — ambiguity — decimal fields (`ratio_pct`, commission caps, `fx_rate_to_usd`) render as JSON numbers, integral values rendered without a fractional part — implementation/services/common.py:116-123
- §2.7 — insert — ambiguity — omitting `expected_third_party_version`/`expected_policy_version` → `ERR_VALIDATION` — implementation/routes/third_parties.py:174-176,361-363, routes/config.py:168-170
- §2.8 — insert — ambiguity — ownership not consulted for contract drafting, clause attachment, payment-request submission, or gift-entry registration — implementation/routes/contracts.py:96-141,262-289, routes/operations.py:110-160 (no sponsor check)
- §2.9 — insert — ambiguity — within a priority tier, the §3 endpoint narratives pin the evaluation order — e.g. implementation/routes/third_parties.py:198-202 (ownership→training→policy) vs 228-234 (policy→questionnaire→flags)
- §3.1 — insert — ambiguity — duplicate `country_code` and out-of-range `cpi_score` → `ERR_VALIDATION`; re-score skips parties with null provisional (DRAFT); a DRAFT party receives the sanctions flag/case but keeps `DRAFT` status — implementation/routes/config.py:71-75,107-124, services/core.py:289-295
- §3.2 — insert — ambiguity — registration payload fields validated before the `country_code` lookup — implementation/routes/third_parties.py:113-118
- §3.3 — insert — ambiguity — screening-sourced flags carry a server-composed `description`; all non-MANUAL flags have server-composed descriptions — implementation/routes/third_parties.py:333-337, services/core.py:299-314
- §3.3 — insert — ambiguity — auto-escalation of a manually raised CRITICAL flag records null `escalated_by_user_id`, so SoD does not constrain the decider — implementation/routes/third_parties.py:485, services/core.py:299-313
- §3.4 — insert — ambiguity — acceptance permitted only from `SUBMITTED`; from `ISSUED`/`RETURNED` → `ERR_INVALID_STATE` — implementation/routes/third_parties.py:433
- §3.5 — insert — ambiguity — flags "linked" to a case = every flag of the same third party currently `UNDER_ENHANCED_REVIEW` — implementation/routes/third_parties.py:553-559
- §3.6/§3.7/§3.8 — revise — ambiguity — "the owning sponsor" → "a sponsor" for contract drafting, payment charging, gift registration (ownership only enforced on the four §2.8 actions) — implementation/routes/contracts.py:96-98,262-264, routes/operations.py:110-112
- §3.6 — insert — ambiguity — contract born with empty `clause_codes` list — implementation/routes/contracts.py:118
- §3.8 — insert — ambiguity — gift field validation precedes the sanctions/temporal/cap refusal chain — implementation/routes/operations.py:122-137 vs 131-144
- §3.8 — insert — ambiguity — `gov_gift_rolling_12m_cents` window anchored at the latest `event_date` among approved government-official entries; 0 when none exist — implementation/services/core.py:377-394
- §3.9 — insert — ambiguity — manual cycle openable against any non-terminal party; only `SCHEDULED`→start and `IN_PROGRESS`→complete, so an `OVERDUE` cycle accepts neither — implementation/routes/operations.py:228-259
- §3.9 — insert — ambiguity — audit notice against a non-terminal non-APPROVED party → `ERR_THIRD_PARTY_NOT_APPROVED` — implementation/routes/operations.py:309-312
- §3.9 — insert — ambiguity — a BusinessSponsor completing another operator's assignment → `ERR_UNAUTHORIZED_ROLE` — implementation/routes/operations.py:440-441

**Mismatch-revisions**:
- §2.9 — revise — mismatch — tier-3 `country_code` resolution at registration now explicitly occurs after the registration payload's own field validation (impl validates body before the lookup) — implementation/routes/third_parties.py:113-118
- §2.9 — revise — mismatch — outcome/disposition selectors are parsed before the state-machine tier, so an unknown selector yields `ERR_VALIDATION` even against a terminal entity — implementation/routes/third_parties.py:302-303,496-497,535-537, routes/operations.py:257-259
- §3.1 — revise — mismatch — "Flipping `sanctioned` to true" → whenever an update carries `sanctioned: true`, whether or not the stored value changes — implementation/routes/config.py:99-100,118
- §3.6 — revise — mismatch — certification issuance against REJECTED/TERMINATED party: `ERR_INVALID_STATE` → `ERR_ALREADY_TERMINAL` — implementation/routes/contracts.py:195
- §3.9 — revise — mismatch — audit create validates end-after-start (`ERR_VALIDATION`) before the ten-day notice rule, inverting the strict §2.9 temporal-over-validation reading — implementation/routes/operations.py:315-320

Not changed (already uniquely pinned by the PRD and verified against impl): all scoring formulas and tier thresholds, screening cascade severity mapping and auto-advance guard, OCC semantics on the three writes, commission bracket order and REIMBURSEMENT exemption, gift window inclusivity and dual thresholds, termination cascade contents, re-diligence intervals and DOWNGRADE ladder, audit notice/overlap half-open math, sweep comparison directions, the endpoint/role table, and the error catalogue.

---

PIPELINE COMPLETE — all 9 steps done. Final state: 8/8 sweep rounds × 85/85 tests passing; workspace/PRD_COMPLETED.md written.
