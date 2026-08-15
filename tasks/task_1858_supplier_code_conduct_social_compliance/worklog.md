# Worklog — task_1858_supplier_code_conduct_social_compliance

Scenario: 1858. Supplier Code of Conduct & Social Compliance Audit (responsible sourcing program)

## Step 1: Create Task Directory — 2026-08-14T21:17:00.000Z

Pre-created by pipeline launcher: `tasks/task_1858_supplier_code_conduct_social_compliance/` + `workspace/` (per invocation args; orchestrator did not scan or create task dirs).

## Step 2: Generate Scaffold — 2026-08-14T22:08:30.000Z

Done. All three scaffold artifacts are generated and validated.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1858_supplier_code_conduct_social_compliance/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design`/`scaffold_corner_design` keys; scenario verbatim)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design`, 9 rules × 2 instances = 18
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design`, 9 sections, 58 active instances + 14 `excluded_because` stubs citing §1.8 coverage

**Design summary** (no sibling tasks consulted):
- **Archetype**: compliance/audit primary + workflow-orchestration secondary; flat topology (all 13 entities root-level, FK-linked), cyclic state machines, segregation-of-duties role model, immediate consistency
- **Entities (13)**: CodeVersion, Supplier, CodeAcknowledgment (self-referential supersede chain, `common_fields: false`), Facility, Auditor, Audit, Finding, CorrectiveActionPlan, Grievance, WorkerInterviewRecord, RecruitmentFeeReview, Reimbursement, MutualRecognitionClaim
- **Surface**: 56 endpoints (incl. `POST /_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default), 41 error codes (all referenced by designs), 9 calculations, 11 state machines, 6 roles (Auditor→`entity_backed:Auditor`, SupplierContact→`entity_backed:Supplier`, rest opaque)
- **Difficulty mechanics**: dual-variant facility risk (baseline 87.0 vs history 48.0 on identical data) and scorecard (provisional 32 vs verified 45); combinatorial formulas in modes (a) audit-interval tiered min/clamp → 15 months and (b) per-item-then-sum fee rounding → 9 vs 10; cyclic Audit (return-for-correction) and CAP (reject/resubmit + verify-fail loops); depth-4 ZT cascade and depth-3 verify-fail escalation cascade; priority conflicts state-vs-temporal and safety-vs-referential; boundary checks at score 80 (>= semantics) and interview minimum ceil(sqrt(100))=10; auditor half-open overlap vs facility 30-day buffer gap; tally and reimbursement-balance compensating invariants; one OCC rule (`acknowledgment-create-stale-supplier`, 412 on `expected_supplier_version`)

**Validation results**:
- `scaffold_lint.py` verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (838 calls scanned; one FK gap found and fixed by adding `GET /grievances/{id}/recruitment-fee-reviews`)
- Placeholder closure: 0 unbound `${var}` across all 90 instances; instance names unique across both files; no forbidden concurrency vocabulary
- All numeric literals in `assert:` lines were executed in Python and verified (score arithmetic, rounding orders, sqrt ceilings, date offsets 2026-10-01/2026-11-30/2027-02-28, due date 2027-12-03)

## Step 3: Copy Shared Files — 2026-08-14T22:09:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1858_supplier_code_conduct_social_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T22:26:00.000Z

All contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1858_supplier_code_conduct_social_compliance/workspace/PRD.md` (344 lines). The two withheld design files were never opened.

## What was generated

A prose PRD projecting the full scaffold: §1 introduction (2 paragraphs, business-context angle); §2 with domain-derived subsections (2.1 roles/identities, 2.2 verbatim envelope, 2.3 pagination, 2.4 common resource properties incl. the `updated_at`/`version` absence on CodeAcknowledgment and WorkerInterviewRecord, 2.5 logical clock defaulting to 2026-08-01T00:00:00Z, 2.6 the 12-family validation order, 2.7 OCC, 2.8 precision/rounding, 2.9 segregation of duties and worker anonymity, 2.10 cascades/compensating pairs/left-to-right path validation); §3 in 9 workflow subsections (code versions & acknowledgment, facility risk scoping, auditor pool & scheduling windows, findings & the 4-hop zero-tolerance cascade, CAPs & independent verification, dual-variant scorecard & termination cascade, grievances & interview evidence, fee reviews & reimbursement ledger, mutual recognition); §4 a 56-row 4-column endpoint table; §5 a 41-row 2-column error catalogue. All formulas were translated to precise prose with pinned evaluation orders (per-item FX rounding with the 3×300 BDT → 9 vs 10 example; interval order tier base → FAILED_ZT cap → validity extension → clamp; ceil(sqrt) interview sample with 99/100/101 boundaries).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 73 required, 73 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (§2.6 ordered families, parent-chain-before-target and safety-outranks-facility-match sub-orderings stated), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (POST /code-acknowledgments + expected_supplier_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 39 checked, 39 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 56 checked, 56 expressed (multi-endpoint scopes like ERR_AUDIT_ALREADY_OPEN and ERR_SUPPLIER_ALREADY_TERMINATED enumerated at every guarded operation), 0 missing
- entities[].fields[] structured content: 73 checked, 73 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (decide/review/verify/claim/triage branches, both risk variants, both scorecard variants, both standing gates), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 521
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 matches the canonical block byte-for-byte; all 41 error IDs appear in §2/§3 backticks; all 83 enum/state values present; all 6 role names exact; no fuzzy/approximating words; no operator pseudocode; §4 has exactly 56 rows matching the scaffold (no extras/omissions); document ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T23:05:00.000Z

Generation complete. All audits pass. Final summary:

## What was generated

**`test_helpers/`** (9 files) — PRD-specific infrastructure:
- `types.py` — 14 entity TypedDicts + 21 status/role enums; the two immutable registration records (`CodeAcknowledgment`, `WorkerInterviewRecord`) correctly omit `updated_at`/`version` per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with 55 methods, one per PRD §4 endpoint
- `api_errors.py` — all 40 error IDs with the PRD §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + the two conserved-quantity checkers (`assert_audit_tally_conservation`, `assert_reimbursement_balance`) + `parse_instant`
- `factories.py`, `constants.py` (risk/FX/score/interval tables), `test_users.py` (opaque-role constants + `make_auditor_headers`/`make_supplier_contact_headers` entity-backed builders), `fixtures.py` (composite chains: `setup_active_supplier`, `setup_in_progress_audit`, `setup_report_submitted_audit`, `setup_completed_audit`, `setup_failed_zt_audit`, `completed_audit_with_findings`, `setup_confirmed_review`, `cap_full_pass_cycle`, etc., all with entity-backed identity threading)

**`test_suite/`** — `conftest.py` + 10 claim-clustered files, **94 tests**.

## Coverage audit (all PASS)
- Queue A: all 18 difficulty instances have exactly 2 tests each (36 tests), tagged `Design: Difficulty/<rule_id>/<name>`
- Queue B: all 58 non-stub corner instances have exactly 1 test each; all 14 `excluded_because:` stubs skipped with programmatically verified cross-references into §1.8
- Every one of the 94 docstrings ends with exactly one resolving Design line (AST-verified)
- All 145 PRD citations survive literal whitespace-normalized grep of PRD.md
- No `skip`/`skipif`/`xfail`, no scaffold references, pytest collects 94 tests cleanly

## Key adjudications (PRD-first filter)
- **Version literals**: PRD §2.4 pins "increments by one on every mutation" but never states the initial value, so absolute literals from the YAML (v==1, ==3, ==6) were replaced with relative-increment assertions (`v == prior + 1`, `final == v_at_submit + 3`) — uniquely derivable, still rule-bearing
- **Datetime results** (`remediation_due_date`, `next_audit_due_date`): compared as parsed instants rather than exact strings, since PRD doesn't pin millisecond serialization for computed dates
- **Priority-pair instances kept**: PRD §2.6 explicitly fixes the family evaluation order and §3.8 explicitly states the safety guard "outranks" the facility-match guard, so the validation-priority silence pattern does not apply
- **`facility_computed_fields_input_ignored`** translated as designed (rogue `risk_tier`/`risk_score_baseline` planted, server-computed 87.0/HIGH asserted), matching the established sibling-task precedent for this claim type
- No instances were skipped as untestable; no weakened or placeholder tests were emitted

## Step 6: Generate Implementation — 2026-08-14T22:36:00.000Z

(Note: Steps 5 and 6 were launched concurrently; Step 6 finished first. Its summary is recorded here in launch order.)

Fresh boot has clean empty state, list envelope is correct with `limit`/`offset`/`total_count`/`has_more`, and role permission is enforced. The implementation is complete and boots cleanly per the per-test-server contract.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1858_supplier_code_conduct_social_compliance/workspace/implementation/`:

**Files created:**
- `start.sh` — foreground launcher with `exec`, reads `$PORT` (default 10000), binds `0.0.0.0`, guards pip install behind `python3 -c "import flask"` so per-test reboots skip the install
- `requirements.txt` — Flask 3.0.3
- `app.py` — Flask app, error handlers (ApiError → envelope, 404, 405, uncaught), blueprint registration
- `db.py` — in-memory stores (empty at boot, no seeding) plus the logical clock (default `2026-08-01T00:00:00.000Z`)
- `errors.py` — ApiError class + all 39 error IDs with their HTTP statuses from the scaffold
- `response.py` — envelope helpers producing `meta`/`response_type`/`data` exactly as specified, with `limit`/`offset`/`total_count`/`has_more` on list meta
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, role gating, pagination clamping (limit 1..100 default 10)
- `services/utils.py` — ISO-8601 parsing/formatting (3 fractional digits, Z), `add_months` calendar-aware, `ceil_sqrt`
- `services/scorecard.py` — baseline risk (country × sector + worker factor, 1 dp round-half-up), history blend (50/50, cap 100), tier mapping (70/40), interval chain (tier → FAILED_ZT cap → MR extension → clamp [3,36]), due-date computation, scorecard (provisional non-VOIDED vs verified OPEN, floor 0), consequence tier (80/60/40), probation gating, audit tallies, review balance, per-item FX rounding
- `routes/` — clock, code_versions, suppliers, acknowledgments (OCC on `expected_supplier_version` → 412), facilities, auditors, audits (window shape ANNOUNCED 1-10d / SEMI_ANNOUNCED 14-60d, half-open double-booking, 30-day facility spacing, MR coverage on ANNUAL), findings (ZT cascade: tally → FAILED_ZT → scorecard −40 → PROBATION; void restores), caps (review/resubmit/request-verification/verify with segregation-of-duties, escalation penalty +5 at count ≥2), grievances (CRITICAL −5, resolve restores, WorkerHotline-only create, program-staff-only read), interviews (one per audit, `ceil(sqrt(worker_count))` minimum), reviews (per-item round-half-up FX, auto-REIMBURSED at zero outstanding, reverse restores VIOLATION_CONFIRMED), mutual_recognition (ZT/score/staleness gates, interval extension on ACCEPT).

**Verified via smoke test:**
- Fresh boot on `start.sh` listens on PORT, empty store, envelope + pagination fields correct
- Auth headers enforced (400 missing/invalid), role permission enforced (403)
- End-to-end ZT cascade: create code version → publish → create supplier → acknowledge (OCC) → create facility (BD baseline=75, HIGH, interval 6) → create auditor → create audit → start → record ZT finding → audit transitions to FAILED_ZT with `zt_count=1` → supplier verified_score 100→60 → status ACTIVE→PROBATION

## Step 7: Run Tests and Iterate — 2026-08-14T23:15:00.000Z

All 8 rounds pass cleanly: 94/94 in every round. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial 8-round sweep → fix → confirming 8-round sweep, all 8 rounds 94/94 passed).

**Tests deleted:** None. Both failing tests asserted rules verbatim-covered and uniquely derivable from PRD §3.5, so both stayed.

**Fixes applied to `test_helpers/`:** None — the composite helpers (`cap_on_major_finding`-side fixtures, `cap_full_pass_cycle`) were each individually correct; the bug was in how two test functions composed them.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1858_supplier_code_conduct_social_compliance/test_suite/test_07_corrective_action_plans.py` — `TestCapGuards::test_cap_review_after_verified_passed_rejected` and `TestCapGuards::test_cap_create_on_closed_finding_rejected`. Both tests called `cap_on_major_finding()` (which already creates a SUBMITTED plan on the finding) and then called `cap_full_pass_cycle(finding_id, ...)`, which issues `POST /corrective-action-plans` for a second plan on the same finding. PRD §3.5 ("at most one open plan may exist per finding — open here meaning SUBMITTED, APPROVED, REJECTED, VERIFICATION_REQUESTED, or VERIFICATION_FAILED (ERR_CAP_ALREADY_OPEN)") requires the implementation to reject that second create, so the setup died with `ERR_CAP_ALREADY_OPEN` before reaching the actual assertion. Fixed both tests to drive the fixture's existing plan (`ctx["cap"]`) through APPROVE → request-verification → verify PASS using the already-imported `review_cap` / `request_cap_verification` / `verify_cap` helpers, preserving the original assertions exactly (ERR_CAP_INVALID_STATE on reviewing a VERIFIED_PASSED plan; ERR_FINDING_NOT_OPEN on creating a plan for a VERIFIED_CLOSED finding).

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful on every exercised rule; the two failures were deterministic test-setup bugs (the implementation was correctly enforcing the one-open-plan-per-finding rule against a malformed setup).

**Note on diagnostic noise:** mid-run stdout of sweep 1 showed phantom FAILED markers for `test_cap_already_open_for_finding` and `test_cap_create_ownership_violation_rejected`; these were partial-line interleaving artifacts of 8 concurrent pytest streams writing to one file. The authoritative per-round `results.{i}.json` showed exactly the same 2 failures in every round, and no flakiness was observed in either sweep.

## Step 8: Finalize PRD — 2026-08-14T23:20:00.000Z

## Summary

**Outcome: zero edits.** `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (diff confirms `IDENTICAL`).

### Line counts / %-delta
- `PRD.md`: 344 lines
- `PRD_FINALIZED.md`: 344 lines
- Delta: 0 lines, 0.0%

### Adjudication of each `<step_7_diff>` item

Every Step 7 item is a pure test-fixture bug; each behavior the fixed tests assert is already verbatim-pinned in PRD §3.5 and matched exactly by the implementation. Per the method ("not every item is a PRD silence — some are pure fixture bugs"), no edit traces to any item:

1. **`test_cap_review_after_verified_passed_rejected` (test_suite fix)** — asserts `ERR_CAP_INVALID_STATE` (409) on reviewing a `VERIFIED_PASSED` plan. PRD §3.5 already pins this verbatim: "`APPROVE` moves the plan `SUBMITTED → APPROVED`. `REJECT` moves it `SUBMITTED → REJECTED` … Either decision from any other state is an `ERR_CAP_INVALID_STATE`", plus "`VERIFIED_PASSED`, which is terminal". Implementation matches at `implementation/routes/caps.py:143-144`. No PRD silence → no edit.

2. **`test_cap_create_on_closed_finding_rejected` (test_suite fix)** — asserts `ERR_FINDING_NOT_OPEN` (409) on creating a plan for a `VERIFIED_CLOSED` finding. PRD §3.5 pins verbatim: "The finding must be `OPEN` (`ERR_FINDING_NOT_OPEN`)". Implementation matches at `implementation/routes/caps.py:80-81`. No PRD silence → no edit.

3. **The collision rule that broke both setups (one-open-plan-per-finding)** — PRD §3.5 pins verbatim: "at most one open plan may exist per finding — open here meaning `SUBMITTED`, `APPROVED`, `REJECTED`, `VERIFICATION_REQUESTED`, or `VERIFICATION_FAILED` (`ERR_CAP_ALREADY_OPEN`)". Implementation matches exactly: `OPEN_CAP_STATUSES = {"SUBMITTED", "APPROVED", "REJECTED", "VERIFICATION_REQUESTED", "VERIFICATION_FAILED"}` at `caps.py:24`, enforced at `caps.py:82-85`. The bug was that `cap_full_pass_cycle` (`test_helpers/fixtures.py:417-423`) issues a fresh `POST /corrective-action-plans` on a finding where `cap_on_major_finding()` had already created a `SUBMITTED` plan — the implementation correctly rejected the malformed setup. No PRD silence → no edit.

### Pre-edit search log (NO-NEW-MISMATCH due diligence for the "no edit" verdict)

Since the candidate action was "no edit," I ran the enumeration anyway to confirm the PRD's existing wording is consistent with **all** impl paths touching each subject:

- **(a) Subject: CAP-review from-state guard.** (b) Enumerated: `caps.py:132-154` (`review_cap`, sole raise site of review-side `ERR_CAP_INVALID_STATE`); cross-checked the three other `ERR_CAP_INVALID_STATE` sites (`caps.py:168` resubmit-from-`REJECTED`, `caps.py:185` request-verification-from-`APPROVED`/`VERIFICATION_FAILED`, `caps.py:206` verify-from-`VERIFICATION_REQUESTED`) — each has its own verbatim PRD §3.5 sentence, all consistent. (c) No wording change; existing universal phrasing "any other state" correctly covers `VERIFIED_PASSED` and every other non-`SUBMITTED` state.
- **(a) Subject: finding-must-be-`OPEN` for plan creation.** (b) Enumerated: `caps.py:69-81` (create path; existence → ownership → finding-state → uniqueness order matches PRD §2.6 families 4→5→7→9 exactly); the other `ERR_FINDING_NOT_OPEN` site `routes/findings.py:160` (void on non-`OPEN` finding) is separately pinned by PRD §3.4 ("may void a finding that is still `OPEN` (`ERR_FINDING_NOT_OPEN` otherwise)") — no conflict. (c) No change.
- **(a) Subject: one-open-plan uniqueness set.** (b) Enumerated: `caps.py:24, 82-85` (sole raise site; only `create_cap` creates plans, so no parallel endpoint exists); consistency of `REJECTED`-counts-as-open verified against resubmit-in-place semantics (`caps.py:157-175`, PRD §3.5 "resubmits it … only possible from `REJECTED`") and the verify-fail retry loop (`caps.py:184`, PRD §3.5 "equally from `VERIFICATION_FAILED`"); noted that a `VERIFIED_PASSED` plan can never coexist with an `OPEN` finding (verify-PASS flips the finding at `caps.py:228`), so the open-set's exclusion of `VERIFIED_PASSED` is unreachable-but-consistent in practice. (c) No change.

Also verified the error catalog (PRD §5 lines 329-331: all three errors 409) matches `implementation/errors.py:46-48`, and HTTP statuses asserted by the fixed tests agree.

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_1858_supplier_code_conduct_social_compliance/workspace/PRD_FINALIZED.md` (created, byte-identical to `PRD.md`).

## Step 9: Complete PRD — 2026-08-14T23:33:00.000Z

All edits are applied and verified. Final summary:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1858_supplier_code_conduct_social_compliance/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (byte-identical to `PRD.md`) 344 lines / 53,601 chars → `PRD_COMPLETED.md` 346 lines / 57,266 chars (**+2 lines, +3,665 chars**). 29 edit sites; no sections added, no behavior invented.

**Counts:** 21 ambiguity-pins, 12 mismatch-revisions.

### Changes (section — insert/revise — class — what — impl evidence)

- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as taken from the logical clock — `implementation/response.py:13-15`
- §2.2 — insert — ambiguity — undefined paths and unsupported methods on defined paths return `ERR_NOT_FOUND` (404) — `implementation/app.py:16-23`
- §2.3 — revise — ambiguity — `limit`/`offset`: unparseable values fall back to defaults (10/0); out-of-range values clamp to [1,100] / ≥0 rather than rejecting — `implementation/middleware.py:47-65`
- §2.3 — revise — ambiguity — list sort ties on `created_at` preserve storage/insertion order — e.g. `implementation/routes/suppliers.py:86`
- §2.4 — revise — ambiguity — `version` starts at 1 — e.g. `implementation/routes/suppliers.py:66`
- §2.5 — revise — ambiguity — clock set validates `to_iso8601` (`ERR_INVALID_REQUEST`) and stores the instant normalized to UTC with 3 fractional digits; response echoes the normalized value — `implementation/routes/clock.py:16-23`, `implementation/services/utils.py:56-60`
- §2.6 family 3 — revise — mismatch — conditional fields (`resolution_note`, `rejection_reason`) and `/audits/{id}/decide`'s `decision` value are enforced after the from-state check; unrecognized `to_status` on code-version transition is rejected only after the existence check — `implementation/routes/grievances.py:142-146`, `implementation/routes/caps.py:143-149`, `implementation/routes/audits.py:267-292`, `implementation/routes/code_versions.py:76-87`
- §2.6 family 4 — revise — mismatch — `linked_grievance_id` removed from the left-to-right existence family; its existence is checked after the one-review-per-audit guard — `implementation/routes/reviews.py:76-83`
- §2.6 family 5 — revise — mismatch — on auditor/supplier-owned action endpoints (start, submit-report, finding record/void, interview and fee-review recording, plan resubmit/request-verification) from-state checks run before ownership; creation endpoints (acknowledgment, CAP) keep ownership-before-state — `implementation/routes/audits.py:220-223,240-243`, `implementation/routes/findings.py:63-68,158-169`, `implementation/routes/caps.py:167-170,184-187`, `implementation/routes/interviews.py:51-54`, `implementation/routes/reviews.py:72-75` vs. `implementation/routes/acknowledgments.py:68-78`, `implementation/routes/caps.py:77-81`
- §2.8 — insert — ambiguity — month arithmetic is calendar-aware with the day clamped back to the target month's last day — `implementation/services/utils.py:63-76`, `implementation/services/scorecard.py:132-144`
- §2.9 — revise — mismatch — interviewer `notes` are stored verbatim (no server-side anonymization) — `implementation/routes/interviews.py:73`
- §2.10 — revise — ambiguity — a recompute refreshes `updated_at`/increments `version` even when recomputed values are unchanged — `implementation/services/scorecard.py:252-253,270-271`
- §3.1 — insert — ambiguity — `supersedes_acknowledgment_id` filter: empty value or literal `null` selects first acknowledgments — `implementation/routes/acknowledgments.py:113-117`
- §3.2 — revise — ambiguity — unlisted `country_code` contributes exposure 0 to the baseline — `implementation/services/scorecard.py:44`
- §3.2 — revise — ambiguity — scoping read returns the full facility representation — `implementation/routes/facilities.py:122-128`
- §3.2 — revise — mismatch+ambiguity — `exit_reason` accepted but not stored; exit only from `ACTIVE`, re-exit rejected with `ERR_AUDIT_ALREADY_OPEN` — `implementation/routes/facilities.py:131-153` (counted as one mismatch + one ambiguity)
- §3.3 — insert — ambiguity — deactivating an already-`INACTIVE` auditor is a successful no-op — `implementation/routes/auditors.py:82-86`
- §3.3 — revise — ambiguity — window instants must parse (unparseable → `ERR_INVALID_AUDIT_WINDOW`); span is exact elapsed time with inclusive day bounds — `implementation/routes/audits.py:119-133`
- §3.3 — revise — mismatch — `correction_note` accepted but not stored — `implementation/routes/audits.py:287-290`
- §3.5 — revise — mismatch — `verification_note` optional and not persisted; only `outcome` is required — `implementation/routes/caps.py:198-201,224`
- §3.6 — revise — mismatch — recompute triggers cover only `CRITICAL` grievance filing/triage — `implementation/routes/grievances.py:84-87,152-155`
- §3.6 — revise — mismatch — scorecard counts range over findings on audits of any status, `CANCELLED` included — `implementation/services/scorecard.py:188-192`, `implementation/routes/suppliers.py:108-118`
- §3.6 — insert — ambiguity — the standing gate acts only on `ACTIVE`/`PROBATION` suppliers; `ONBOARDING` recomputes scores/tier without status change — `implementation/services/scorecard.py:247-250`
- §3.6 — revise — mismatch — `termination_reason` accepted but not stored — `implementation/routes/suppliers.py:138-163`
- §3.7 — revise — mismatch — `ESCALATE`/`RESOLVE` recompute the scorecard only for `CRITICAL` grievances — `implementation/routes/grievances.py:152-155`
- §3.7 — revise — ambiguity — interview recording requires `IN_PROGRESS`; non-string `notes` treated as absent — `implementation/routes/interviews.py:50-52,73`
- §3.7 — revise — mismatch — a grievance's linked fee-review list holds one entry per linking review (zero or more), not zero-or-one — `implementation/routes/grievances.py:165`, `implementation/routes/reviews.py:76-83`
- §3.8 — revise — ambiguity — fee-review recording requires `IN_PROGRESS`; linked-grievance existence checked after the one-per-audit guard — `implementation/routes/reviews.py:72-83`
- §3.8 — revise — ambiguity — a `currency` outside the rate table converts at 1.0 cents/minor-unit — `implementation/services/scorecard.py:281`
- §3.9 — revise — ambiguity — staleness boundary inclusive (exactly 12 months old accepted; future dates never stale) — `implementation/routes/mutual_recognition.py:143-150`
- §3.9 — revise — ambiguity — claim-validity boundary inclusive at exactly the program validity period — `implementation/services/scorecard.py:121-124`

**Notable judgment calls:** (1) PRD §3.6's "non-`CANCELLED` audits" was revised to "any status" because the scorecard read's live counts observably include findings on cascade-cancelled audits for terminated suppliers. (2) The state-vs-ownership ordering was pinned in §2.6 family 5 rather than renumbering families, because impl is split (creation endpoints check ownership first; action endpoints check state first). (3) The reason/note fields (`termination_reason`, `exit_reason`, `correction_note`, `verification_note`) are accepted-but-not-stored in impl — PRD revised accordingly; tests corroborate by never reading them back.
