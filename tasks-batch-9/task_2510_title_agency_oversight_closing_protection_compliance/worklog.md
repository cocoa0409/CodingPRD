# Worklog — task_2510_title_agency_oversight_closing_protection_compliance

## Step 1: Create task directory — 2026-09-03T03:15:43.875Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2510_title_agency_oversight_closing_protection_compliance` and its `workspace/` subdirectory. Index 2510 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was self-allocated.

## Step 2: Generate scaffold — 2026-09-03T04:47:58.345Z

All three scaffold artifacts are complete and the linter is clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2510_title_agency_oversight_closing_protection_compliance/SCAFFOLD.yaml` (§1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2510_title_agency_oversight_closing_protection_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2510_title_agency_oversight_closing_protection_compliance/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

The hard constraint was honored: nothing outside `skills/prd-bench-scaffold-generator/**` and this task directory was read.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2510_title_agency_oversight_closing_protection_compliance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2510_title_agency_oversight_closing_protection_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2510_title_agency_oversight_closing_protection_compliance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    45
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1003

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

| Element | Count |
|---|---|
| Entities (§1.1) | 11 — Agency, StateProgram, AgencyAppointment, ClosingProtectionLetter, PolicyFile, RemittanceStatement, RemittanceLine, EscrowAccount, EscrowAudit, AuditFinding, AgencyClaim |
| State machines (§1.2) | 12 across 9 entities (Agency and PolicyFile carry 2 and 3 independent dimensions) |
| Concurrency rules (§1.2.1) | 3, all `expected_agency_version` on Agency → `ERR_STALE_AGENCY_VERSION` 412 |
| Calculations (§1.3) | 14 (2 with declared variants) |
| Validations (§1.4) | 62 across 12 priority rungs (10 → 130) |
| Endpoints (§1.5) | 45 |
| Errors (§1.6) | 56 |
| Roles (§1.7) | 5 — AgencyPrincipal (entity-backed), LicensingAnalyst, EscrowAuditor, UnderwritingCounsel, ComplianceOfficer |
| §1.8 instances | 18 (9 rule blocks × 2) |
| §1.9 instances | 71 = 60 executable + 11 `excluded_because` stubs, over all 9 taxonomy sections (entities 11, state_machines 13, calculations 10, validations 8, endpoints 5, errors 11, rbac 6, cross-cutting 6, consistency 1) |

Verified programmatically: no duplicate instance names across §1.8 ∪ §1.9; every stub's cited `difficulty_instance` exists by name in §1.8; every stub omits `test_recipe`; all 56 error ids are exercised by at least one instance; the 4 list endpoints not driven by a structured `call:` are still asserted as reads.

## Design adjudications

- **Complexity profile**: primary archetype `compliance_audit`, secondary `ledger_reconciliation`; layers `dual_variant_calculation`, `cascading_side_effects`, `rate_threshold_triggers`, `optimistic_concurrency`; topology `flat`; machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`.
- **Parallel over hierarchical**: PolicyFile carries three independent dimensions (`issuance_status`, `remittance_status`, `transfer_status`) and Agency two (`appointment_status`, `financial_review_status`), so a single row advances on several axes at once instead of one long linear chain.
- **Two-scope defalcation score**: `rolling_window_365` fires on audit closure (ignores finding status), `lifetime_uncleared` fires on actor-initiated `POST /escrow-audits` (excludes CLEARED, no window); system-created successor audits deliberately do not recompute. Thresholds 60 / 30 with a 100 cap.
- **Per-line rounding is the pinned trap**: premium splits `round_half_up` per line then sum (3 × 33333 @ 0.80 → 26666/6667 each, totals 79998/20001), so sum-then-round (79999/20000) is a detectable wrong answer.
- **Two variance methods**: SURPRISE audits use `STRICT_THREE_WAY` (max of the three pairwise absolute differences), SCHEDULED use `BANK_TO_TRIAL` — same inputs, different answers.
- **Claim tier pinned from gross loss**: the waterfall computes tier from `loss / eo_limit` and must not re-derive it from the net-of-indemnity exposure (the re-derivation path is spelled out as the forbidden answer).
- **Deliberate near-miss in posture**: E&O expiry is excluded from `agency_oversight_posture` even though it blocks new coverage at priority 100, so posture and coverage-eligibility are not interchangeable.
- **Referral escape hatch**: `ERR_UNDERWRITING_AUTHORITY_EXCEEDED` is lifted when `referral_decided_by_user_id` is non-null, which makes the authority check depend on the outcome of the referral routing that runs before it, and keeps the error reachable only via an inflated `approved_liability_cents` at issuance.
- **Two segregation-of-duties rules with different shapes**: SoD-1 (audit opener ≠ closer) only bites the ComplianceOfficer who used the shared create permission; SoD-2 (referral approver ≠ claim adjudicator) is scoped to one policy file and blocks both adjudication outcomes, not just the adverse one.
- **Four conserved ledgers** (`cpl_outstanding_exposure_cents`, `unremitted_premium_cents`, `unreported_policy_count`, `pending_transfer_count`) with exact-restoration corners on letter void and statement reopen, so compensation is asserted as arithmetic identity rather than "roughly reversed".

Two small SCAFFOLD.yaml corrections were made while closing lint findings: `RemittanceStatement.unreported_premium_cents` was added as a declared computed field (it was produced by the reconciliation formula but never declared), and `AgencyClaim.net_underwriter_exposure_cents`'s description was aligned with the calculation's step 4. Path placeholders in §1.5 were normalized to the skill's `{id}` convention, which is what check (f) requires for sub-resource reverse-reachability.

## Step 3: Copy shared files — 2026-09-03T04:48:25.180Z

Copied `./INSTRUCTION.md` to `tasks/task_2510_title_agency_oversight_closing_protection_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T05:05:00.000Z

PRD generation is complete and verified.

**Output:** `workspace/PRD.md` — **426 lines**, ~102 KB. Ends at the final row of the §5 error table (a real section boundary, not mid-sentence/table/list). The two forbidden design files were never opened, grepped, or referenced.

## Section list
- `# Title Agency Oversight API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Money/Percentages/Rounding, 2.6 Oversight Posture, 2.7 Cascade Discipline and Conserved Ledgers, 2.8 OCC on the Agency Oversight File, 2.9 Segregation of Duties, 2.10 Path and Body Reference Resolution, 2.11 Validation Precedence
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Onboarding/financial review/appointment, 3.2 State programs, appointments, license verification, 3.3 Closing protection letters, 3.4 Policy files, 3.5 Remittance, 3.6 Escrow accounts and the three-way audit, 3.7 Findings, remediation, risk tiers, defalcation score, 3.8 Claims: recourse and indemnity, 3.9 Termination and file transfer
- `## 4. API Endpoint Definitions` — preamble + 45-row, 4-column table
- `## 5. Error Codes` — preamble + 56-row, 2-column table

## Hard contract reports
- **Contract 1 (Field-Name Coverage): PASS.** 136 required identifiers (121 entity fields incl. the 4 common fields, plus every `input`/`query_params`/`path_params` name across all 45 endpoints) checked against 360 distinct backticked tokens in the PRD, with fenced code blocks excluded from the tick-pairing scan. Two independent passes; **0 missing.** First pass surfaced exactly one gap — `to_state` — which was fixed by adding a paragraph to §2.10 covering the transition-request key and its `decision` exception on the appointment endpoint; second pass clean.
- **Contract 2 (Rule Coverage): PASS.** All 62 state transitions, 14 calculations, 62 validation rules (via their 56 error ids, all present), 3 named cascades with every hop, both conserved ledgers, the OCC rule on 3 endpoints, both SoD rules, both designed priority conflicts (P1 posture-freeze over coverage cap; P2 E&O lapse over no-active-appointment), all `applies_to` scopes, and sibling-branch symmetry (both reopen branches, both closure branches, both claim adjudication branches, both transfer completion paths). 84 enum/state values checked; the only absentees are the 6 values belonging to the discarded side of an adjudicated contradiction (below).
- **Contract 3 (§3 Path Purity): PASS.** 268 distinct backticked tokens in the §3 region: 0 start with `/`, 0 are bare HTTP methods, 0 are method+path pairs. No un-backticked path strings in §3 either. Paths appear only in §2.1/§2.8/§2.10 and §4, where the spec permits them.

## Coverage confirmation
- **Endpoints:** 45/45 §1.5 paths present (all in §4; 11 creates documented as 201, the other 34 as 200; root-level topology, no prefix).
- **Errors:** 56/56 §1.6 ids present in §5, and every one is also motivated in §2 or §3 prose.
- **Validations:** all 62 reflected, with the full 14-tier precedence ladder (10 auth → 130 fiscal) written out in §2.11.
- No fuzzy quantifiers, no pseudocode, no leaked scaffold metadata.

## Adjudications (scaffold self-contradictions resolved)
1. **`coverage_scope` / `cpl_scope_allowed` domain** — entity gloss says `LENDER_ONLY | LENDER_AND_BUYER | LENDER_BUYER_SELLER`; validation @30 and the coverage calculation's scope-factor map say `{FULL_SETTLEMENT, LENDER_ONLY, SELLER_PROCEEDS}`. Chose the calculation's three (factors 1.00 / 0.80 / 0.60) and treated `cpl_scope_allowed` as a non-empty array — the only reading under which coverage approval is total.
2. **`referral_reason` labels** — entity lists 3 (`COVERAGE_ABOVE_AGENCY_AUTHORITY`, `COMPLEX_TITLE_FLAGGED`, `AGENCY_POSTURE_RESTRICTED`); the routing calculation gives 4 ordered labels. Chose the calculation's `COMPLEX_TITLE`, `STATE_REFERRAL_THRESHOLD`, `AUTHORITY_LIMIT`, `RESTRICTED_POSTURE`.
3. **`EscrowAudit.critical_finding_count`** — chose the calculation: severity `CRITICAL` **and** status ≠ `CLEARED`, consistent with `Agency.open_critical_finding_count`.
4. **`EscrowAudit.risk_tier` vocabulary** — entity says `LOW | ELEVATED | HIGH | CRITICAL`; the calculation emits `LOW | MEDIUM | HIGH | CRITICAL` with a full four-branch ladder. Chose the calculation (`MEDIUM`, not `ELEVATED`), since the entity's "highest severity among findings" gloss cannot produce the `open_finding_count >= 1` branch.
5. **`AuditFinding.is_repeat`** — chose the calculation's definition (any earlier finding with the same `code` whose parent audit shares the `escrow_account_id`, has a different id, and a strictly earlier `created_at`) over the entity's narrower `follow_up_of_audit_id`-only reading.
6. **`RemittanceLine.underwriter_share_cents`** — chose the calculation: retention is rounded first, then the underwriter share is the remainder. The scaffold's own worked example (12012 at 0.875 → 10511 / 1501) confirms this and refutes the entity-field formula, which would give 1502.
7. **`premium_split_agency_pct` range** — entity constraint says `0 < value < 1`; validation @30 and the error catalogue say `[0,1]`. Chose the closed interval `[0, 1]` inclusive, at most three decimals, rejection `ERR_INVALID_REQUEST`.
8. **§1.7 `exclusive_operations`** — rendered as transition-role rules for all four appointment decisions (only `LicensingAnalyst` may appoint/suspend/reinstate; only `ComplianceOfficer` may terminate), even though validation @55's prose spells out only the terminate half.
9. **E&O check on the `ABSORBED` branch** — the claim state machine lists the `eo_policy_limit_cents > 0` precondition only on `RECOURSE_DEMANDED`, but validation @100's `applies_to` covers `to_state IN {RECOURSE_DEMANDED, ABSORBED}`. Applied it to both branches (also required for absorption's still-computed `recourse_tier`).

### Orchestrator anti-truncation verification (independent of subagent claim)
Ran a programmatic check: all 56 real §1.6 error ids present in PRD.md; all 35 distinct §1.5 path templates present; §5 table holds exactly 56 `ERR_` rows; file ends on a complete table row. The single scaffold token reported "missing" was a compound alternation string (`ERR_AGENCY_NOT_FOUND | ERR_STATE_PROGRAM_NOT_FOUND | ...`) used as a multi-error annotation, not a real error id — its members are all individually present. **Verdict: not truncated; no regeneration needed.**

## Step 6: Generate implementation — 2026-09-03T05:56:00.000Z

(Recorded before Step 5 because Step 5 and Step 6 were launched concurrently and Step 6 returned first.)

The implementation is complete, boots cleanly from a fresh process, and was exercised end to end against every PRD worked example.

## Files written (all under `workspace/implementation/`)

| File | Lines | Role |
| --- | --- | --- |
| `start.sh` | 10 | Launcher: `PORT` (default 10000), binds `0.0.0.0`, guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 81 | App factory, blueprint registration, per-request lock + `tx.begin()`, `ApiError`/`HTTPException`/catch-all handlers with rollback |
| `db.py` | 190 | In-memory `Store` (dicts keyed by id), id/timestamp minting, logical clock (`2026-08-01T00:00:00Z` default), ISO-8601-with-3ms formatting |
| `errors.py` | 137 | All 56 error ids with HTTP statuses and default messages |
| `calc.py` | 269 | Every calculation (Decimal/ROUND_HALF_UP, ROUND_FLOOR caps, exact `Fraction` tier ratios) |
| `derive.py` | 361 | Counters, conserved ledgers, posture, both defalcation-score variants, CASCADE-A, CASCADE-B, transferee eligibility |
| `tx.py` | 76 | Snapshot-diff commit (exactly one version/`updated_at` bump per changed row per request) + rollback |
| `response.py` | 58 | `meta`/`response_type`/`data` envelope, list meta, error envelope |
| `middleware.py` | 66 | Tiers 1, 2, 6, 7, 8 (auth, endpoint RBAC, ownership, transition role, SoD) |
| `shape.py` | 262 | Tier 3 validators + pagination (`limit` 1–100 default 10, `offset` >= 0, never clamped) |
| `lookup.py` | 74 | Tier 4/5 resolution per §2.10 + generic terminal/transition guard |
| `routes/agencies.py` | 244 | §3.1 |
| `routes/state_programs.py` | 156 | §3.2 |
| `routes/cpl.py` | 208 | §3.3 |
| `routes/policy_files.py` | 269 | §3.4 + transfer dimension |
| `routes/remittance.py` | 386 | §3.5 incl. CASCADE-C and both reopen paths |
| `routes/escrow.py` | 486 | §3.6 + §3.7 (accounts, snapshots, audits, findings) |
| `routes/claims.py` | 199 | §3.8 |
| `routes/clock.py` | 20 | `POST /_clock/set_current_utc` |

Total 3,553 lines. Storage is purely in-memory; nothing is seeded, and a fresh boot answers `GET /agencies` with `total_count: 0`.

## Coverage

- **Endpoints:** programmatic diff of the Flask URL map against the §4 table — **45/45 present, 0 extra** (paths and methods identical).
- **Errors:** programmatic diff against §5 — **56/56 ids present, 0 extra, all HTTP statuses match**, every id has a message.
- **Calculations verified live:** CPL four floored caps (90,000,000 `LENDER_ONLY` vs 100,000,000 cap -> 80,000,000); per-line-then-sum premium split (3 x 33,333 @ 0.800 -> 26,666/6,667 per line, 79,998/20,001 totals); issuance timeliness (30 elapsed days = `ISSUED`); reconciliation worked example (expected 599,999, variance 500,000, 1 unreported, penalty 50,000); strict three-way variance 20,000 vs bank-to-trial 5,000; claim waterfall tier pinning (200,000,000 limit, 40,000,000 loss, `AGENCY_ERROR` -> `TIER_1`/20,000,000/12,000,000/20,000,000); ledger conservation (`unremitted_premium_cents` 599,999 -> 500,000 on settle -> exactly 599,999 on reopen).
- **Validations verified live:** ladder order, `ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE`, SoD-1, SoD-2 wiring, OCC, `ERR_TERMINATION_REASON_REQUIRED`, settlement identity, recovery ceiling, duplicate keys, pagination rejection, 401/403/404 tiers, CASCADE-B (appointments `WITHDRAWN`, accounts `CLOSED`, files `PENDING_TRANSFER`, count 1 -> 0 after transfer), transferee re-test at transfer time.

## Adjudications

1. `cpl_scope_allowed` / `coverage_scope` domain and `referral_reason` labels follow PRD §3.2–§3.3 (`FULL_SETTLEMENT|LENDER_ONLY|SELLER_PROCEEDS`; `COMPLEX_TITLE`/`STATE_REFERRAL_THRESHOLD`/`AUTHORITY_LIMIT`/`RESTRICTED_POSTURE`), not the scaffold entity table's stale enums.
2. `underwriter_share_cents` = reported - rounded retention (never `round(reported x (1-pct))`).
3. `premium_split_agency_pct` accepted on the closed interval `[0, 1]` per §2.5 (scaffold said open); extra decimal places are not rejected since §2.5 names rejection only for out-of-interval values.
4. CASCADE-B closes only `OPEN` escrow accounts, literally per §3.9 — accounts already `RESTRICTED` from a prior suspension stay `RESTRICTED`.
5. `EscrowAudit.risk_tier` uses `LOW/MEDIUM/HIGH/CRITICAL` per §3.7; the entity's `ELEVATED` is unreachable.
6. Auto-finding tolerance reads the state program of the agency's oldest `ACTIVE` appointment; with no `ACTIVE` appointment it falls back to 0, so a positive variance still raises a finding.
7. Terminal-dimension check precedes the declared-transition check so both `ERR_ALREADY_TERMINAL` and `ERR_INVALID_STATE` stay reachable.
8. Agency `unreported_policy_count` mirrors the most recently reconciled statement whose status is still `RECONCILED` (so it changes on settlement, as CASCADE-C hop 4 asserts).
9. A posture recomputation landing on `FROZEN` from a non-`FROZEN` value restricts `OPEN` accounts everywhere (per §2.7's derived-value chain), except inside CASCADE-B where they close outright; un-restriction happens only at `REINSTATE` and CASCADE-C hop 5.
10. `created_at`/`updated_at` use strictly monotonic wall clock; all domain instants use the logical clock — this keeps `is_repeat`'s "strictly earlier `created_at`" comparison working when the clock is not advanced.
11. Audit submission checks missing snapshot before closed account, following §3.6's explicit prose order rather than the tier-10 inventory order in §2.11.
12. Statement reopen from `RECONCILED` resets only the five reconciliation outputs (not `submitted_at`/`reconciled_at`), literally per §3.5; reopen from `SETTLED` nulls all three timestamps as stated.
13. Transitions the PRD does not narrow are left at the endpoint's role set: statement reopen (`AgencyPrincipal`|`ComplianceOfficer`) and audit closure (`EscrowAuditor`|`ComplianceOfficer`, guarded by SoD-1).
14. `verified_expires_on` absent on a `VERIFY` yields `ERR_LICENSE_EXPIRED` (the conditional-required catalog enumerates five fields and excludes it); requesting `LATE_ISSUED` directly yields `ERR_INVALID_STATE` since timeliness is derived from the single `ISSUED` target.

## Step 5: Generate unit tests — 2026-09-03T06:35:00.000Z

(Launched concurrently with Step 6; returned second, so it is recorded after Step 6.)

Test infrastructure and test suite are complete. Scratch validation scripts removed; nothing under `workspace/implementation/` was read or written.

## Files written

`test_helpers/` (9 files, 2764 lines, 220 public names, flat barrel in `__init__.py`):
`types.py`, `api_client.py` (`API_PREFIX=""`), `api_errors.py` (56 error ids), `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`.

`test_suite/` — `conftest.py` plus 13 test files. **116 collected items from 106 test functions** (the extra 10 are parametrizations inside `test_01`):

| file | collected |
|---|---|
| test_01_agency_onboarding.py | 24 (14 functions) |
| test_02_state_programs_and_appointments.py | 7 |
| test_03_closing_protection_letters.py | 13 |
| test_04_policy_files_and_issuance.py | 9 |
| test_05_remittance_statements_and_lines.py | 10 |
| test_06_reconciliation_and_settlement.py | 7 |
| test_07_escrow_accounts_and_audit_creation.py | 9 |
| test_08_audit_review_and_closure.py | 7 |
| test_09_findings_and_defalcation_score.py | 5 |
| test_10_agency_claims_recourse.py | 4 |
| test_11_termination_and_transfers.py | 8 |
| test_12_oversight_posture_and_concurrency.py | 6 |
| test_13_role_authorization_and_segregation.py | 7 |

## Instance coverage

- **Difficulty (queue A):** 18/18 instances translated, **exactly 2 tests each** (36 `Design: Difficulty/...` tags).
- **Corner (queue B):** 71 instances, 11 of them `excluded_because:` stubs (0 translated, as required). Of the 60 non-stub instances, **59 translated, 1 skipped**.
- **Verification passes:** every one of the 106 test functions carries exactly one verbatim greppable `PRD:` citation and exactly one trailing `Design:` line (whole-suite check: 106 cited docstrings, 0 problems); no dual tags; no tag pointing at a non-existent instance; class docstrings carry neither; no scaffold leakage (`SCAFFOLD`, `§1.8`, `§1.9`, `difficulty_instance`, `test_recipe`, `distinguishing_aspect`) anywhere in `test_suite/` or `test_helpers/`; `pytest --collect-only -q` clean.

**The single skip:** `Corner/errors/issuance_above_the_authority_limit_without_a_referral_returns_422` (corner yaml line 3038). Its trigger posts `approved_liability_cents` on `POST /policy-files/{id}/issuance-state`, a field neither PRD §3.4 nor SCAFFOLD.yaml accepts on that endpoint. Under the PRD, a file routed straight to `PENDING` always has `approved_liability_cents` inside the authority limit, so `ERR_UNDERWRITING_AUTHORITY_EXCEEDED` is unreachable and the asserted 422 is not uniquely derivable. Left as a gap — not weakened, not xfailed, no placeholder.

## Design adjudications

1. `coverage_scope` — SCAFFOLD.yaml §1.1 (`LENDER_ONLY|LENDER_AND_BUYER|LENDER_BUYER_SELLER`) contradicts PRD §3.2/§3.3 and both indices (`FULL_SETTLEMENT|LENDER_ONLY|SELLER_PROCEEDS` at 1.00/0.80/0.60). PRD wins.
2. `referral_reason` — PRD labels (`COMPLEX_TITLE|STATE_REFERRAL_THRESHOLD|AUTHORITY_LIMIT|RESTRICTED_POSTURE`) win over SCAFFOLD.yaml's.
3. `EscrowAudit.risk_tier = ELEVATED` is in the scaffold enum but no PRD sentence ever writes it; excluded from `types.py`.
4. `REFERRAL_APPROVED` does not exist in the PRD: referral approval posts `to_state: "PENDING"`, decline posts `ISSUANCE_DECLINED`.
5. Clock field is `current_utc`, `ComplianceOfficer`-only; rewinding is explicitly permitted (relied on by the lifetime-vs-window score tests).
6. The corner yaml's prose termination reasons ("Voluntary withdrawal") were normalized to the PRD enum `VOLUNTARY`.
7. **CASCADE-B linkage fix:** the termination-cascade recipe creates the PENDING file with no `cpl_id` yet asserts it becomes `VOIDED`; PRD §3.9 hop 5 voids only files whose `cpl_id` is one of the declined letters. My test therefore has that file cite the REQUESTED letter — legal because `ERR_CPL_NOT_ISSUED` guards issuance, not creation.
8. **Finding-authoring state fix:** the exclusive-operations RBAC recipe expects a 201 finding against a `DRAFT` audit, which PRD §3.8 forbids. The two 403 role refusals are asserted while `DRAFT` (role tier 2 outranks state tier 10) and the audit is submitted before the successful authoring.
9. `GET /policy-files?transferee_agency_id=` is a documented filter (PRD lines 227, 337), so the transfer-completion assertion stands despite PRD line 311 naming only the agency filter.
10. Two corner stubs carry mismatched `difficulty_instance` rule_ids (yaml lines 3892, 3900); cross-references still resolve by instance name, so no action taken.

## Step 7: Run tests and iterate — 2026-09-03T06:52:00.000Z

Clean 8-round parallel sweep confirmed.

## Summary

**Iterations run:** 3

**Per-round passed/total (final sweep, all 8 `results.*.json` present on disk):**

| Round | Result |
| --- | --- |
| 1 | 116 / 116 |
| 2 | 116 / 116 |
| 3 | 116 / 116 |
| 4 | 116 / 116 |
| 5 | 116 / 116 |
| 6 | 116 / 116 |
| 7 | 116 / 116 |
| 8 | 116 / 116 |

failed=0, errors=0, skipped=0 in every round.

**Tests deleted:** none. Every failure traced to a defect inside `test_helpers/` (STEP 2), not to PRD silence and not to the implementation — so no test met the deletion criterion.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `_state_codes`: replaced the one-shot 30-entry `iter(_STATE_CODE_POOL)` with an `itertools.cycle` over the full 676-code two-letter space. The finite one-shot iterator exhausted partway through the session, so `next_state_code()` raised `StopIteration` and every test from collection index 53 onward died in setup (60 of 116 failing, identically in all 8 rounds). Cycling is PRD-faithful: PRD §3.2 requires `state_code` unique *across state programs*, and per-test-server isolation wipes all state programs before each test, so uniqueness only has to hold within one test.
- `test_helpers/assertions.py` — `assert_contains_id` / `assert_excludes_id`: added the optional third `context` parameter the call sites in `test_suite/test_07_*` and `test_suite/test_11_*` already pass as a diagnostic label, and threaded it into the assertion message. The helpers accepted only 2 positional args, so 3 tests failed with `TypeError: assert_contains_id() takes 2 positional arguments but 3 were given` before reaching their real assertion. Purely a message-formatting parameter — no assertion was weakened.

**Fixes applied to `implementation/`:** none. The implementation passed all 116 tests unchanged once the two `test_helpers/` defects were repaired; no PRD-required check was touched.

**Notes:** both defects were fully deterministic (identical failure sets across all 8 rounds each iteration), so no flakiness or load-induced failure was observed at any point. The static arity cross-check I ran over `test_suite/` against every `test_helpers/` signature reports 0 remaining mismatches, so no further latent `TypeError`-class fixture bugs are hiding behind tests that currently pass.

### Orchestrator independent verification of the sweep (per known Step 7 over-claim failure mode)
Re-read all 8 `workspace/implementation/results.*.json` directly: 8 files present, each `passed=116 total=116 failed=0 errors=0 skipped=0`, all written within a 1s window at 06:31:10–06:31:11. `grep -c Terminated workspace/sweep.log` = 0 and the log holds 8 distinct `116/116 passed` lines, so the sweep was not reaped and the green result is genuine.

### Step 8 skip-condition adjudication
Step 7 reports **0 `implementation/` fixes** and **0 deletions**, but **2 `test_helpers/` fixes** across **3 iterations** — so this is NOT the zero-iteration case the skill defines as the skip condition (which requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes). Step 8 therefore runs. Its expected yield is low, since both fixes were fixture defects (an exhausted iterator and a helper arity mismatch) that reveal no PRD silence — the honest outcome may be a near-zero diff, and Step 8 is instructed that not every diff item is a PRD silence.

## Step 8: Finalize PRD — 2026-09-03T06:41:00.000Z

## Result: `PRD_FINALIZED.md` is byte-identical to `PRD.md`

- **Line counts:** PRD.md 426 lines -> PRD_FINALIZED.md 426 lines, **0.0% delta**. Both files md5 `875be181522798d2527ab42745865452`.
- **Changes:** none. Both Step 7 fixes were pure `test_helpers/` fixture defects; after tracing each into `implementation/` I found the PRD already uniquely determines what the implementation does, so manufacturing an edit would have introduced a new mismatch for Step 9 to undo.

### Per-item trace (mandatory pre-edit search, run even though no edit resulted)

**Item 1 — `test_helpers/factories.py::_state_codes` (one-shot iterator -> `itertools.cycle`)**

(a) **Subject identified:** the uniqueness scope and validation surface of `StateProgram.state_code`.

(b) **Impl paths enumerated (grep `state_code` across all of `implementation/`, 4 hits total, all read):**
- `implementation/routes/state_programs.py:30` — `state_code = shape.req_str(payload, "state_code")`. Read `shape.py:44-50`: `req_str` enforces presence and `isinstance(value, str)` only — **no** two-letter length check, no case normalization, no non-empty check.
- `implementation/routes/state_programs.py:39-41` — duplicate check iterates `store.all(db.STATE_PROGRAM)` and compares with exact string equality, raising `ERR_DUPLICATE_STATE_CODE`. Scope is **all** state programs (state programs carry no status dimension, so there is no "live subset" nuance), matching PRD §3.2 "unique across all state programs" verbatim.
- `implementation/routes/state_programs.py:46` — persisted as supplied.
- `implementation/errors.py:124` — message only.
- Also confirmed there is **no** `GET /state-programs` list endpoint and no `state_code` query filter anywhere, consistent with PRD §4 (only `POST /state-programs` and `GET /state-programs/{id}`).
- Confirmed the fixture's reliance on wiped state is a harness property, not an impl feature: `test_suite/conftest.py` (25 lines) only re-exports fixtures; the implementation exposes no reset endpoint.

(c) **Wording adjustment:** none needed. PRD §3.2 already states the exact uniqueness scope the impl enforces, and PRD §2.11 tier 3 requires shape checks only for declared type / enum domain / non-negative cents / ISO dates — a plain string `state_code` with no server-side length validation is already what PRD determines. The "two-letter" phrasing in §3.2 describes the key's nature, not an enforced constraint; tightening it into a validated rule would have contradicted `shape.req_str`.

**Item 2 — `test_helpers/assertions.py::assert_contains_id` / `assert_excludes_id` (added optional `context` message parameter)**

(a) **Subject identified:** the list-membership/filtering behavior those two helpers evaluate at their three call sites.

(b) **Impl paths enumerated (all call sites located, then their server-side counterparts read):**
- `test_suite/test_07_...py:176-178` -> `GET /escrow-accounts?agency_id=...`: `implementation/routes/escrow.py:112-125` filters on `agency_id` and `status` only, matching PRD §4 and §3.6.
- `test_suite/test_11_...py:73-74` -> `GET /escrow-accounts?agency_id=...&status=RESTRICTED` after suspension: same handler, plus the suspension cascade PRD §3.1 already fully specifies.
- `test_suite/test_11_...py:372` -> `GET /policy-files?transferee_agency_id=...`: `implementation/routes/policy_files.py:119-144` filters on `agency_id`, `state_program_id`, `cpl_id`, `transferee_agency_id`, all three status dimensions, plus the `closing_date_from`/`closing_date_to` window — exactly the filter set PRD §3.4/§4 enumerates, and `transferee_agency_id` is retained after `TRANSFERRED` as PRD §3.9 implies.
- Read `assertions.py:361-386`: `context` is interpolated into the failure string only; `find_by_id` membership logic is untouched, so no assertion was weakened.

(c) **Wording adjustment:** none needed. The parameter is diagnostic-only and every filter it exercises is already pinned by PRD §4's filter lists.

### Bottom line
Per the task's own note, this is the "correct output is unchanged" case: the diff contained zero `implementation/` fixes, zero test deletions, and two fixture-only repairs whose subjects (global `state_code` uniqueness; `agency_id`/`status`/`transferee_agency_id` list filters) are each already uniquely determined by PRD §3.2, §3.1, §3.4, §3.9 and §4. I deliberately did not widen scope to find edits — Step 9 does the full scan.

### Orchestrator note on Step 9 execution strategy
Because Step 8 produced a zero-delta `PRD_FINALIZED.md`, the entire burden of PRD/implementation reconciliation falls on Step 9. A single-pass Step 9 over 3,553 lines of implementation across 20 files has a known failure mode of silently no-opping (output byte-identical to input, scan never actually performed). Step 9 is therefore run as **three sequential file-partitioned passes**, each editing `PRD_COMPLETED.md` in place and each responsible for a disjoint slice of `implementation/`:
- Pass 1 — cross-cutting core (`app.py`, `db.py`, `tx.py`, `response.py`, `middleware.py`, `shape.py`, `lookup.py`, `errors.py`, `routes/clock.py`) vs PRD §2.
- Pass 2 — `routes/agencies.py`, `routes/state_programs.py`, `routes/cpl.py`, `routes/policy_files.py` (+ the `calc.py`/`derive.py` functions they call) vs PRD §3.1–§3.4.
- Pass 3 — `routes/remittance.py`, `routes/escrow.py`, `routes/claims.py` (+ their `calc.py`/`derive.py` functions, incl. all cascades and ledgers) vs PRD §3.5–§3.9.
Passes are strictly sequential because all three mutate the same output file.

## Step 9: Complete PRD — 2026-09-03T07:20:00.000Z

Run as three sequential file-partitioned passes over a shared `workspace/PRD_COMPLETED.md` (seeded by the orchestrator as a copy of `PRD_FINALIZED.md`). Cumulative: **103,919 -> 125,011 chars (+21,092, +20.3%)**, 426 lines throughout — every edit was an in-paragraph insert or revision, no new sections or paragraphs. **Totals across the three passes: 51 ambiguity-pins, 21 mismatch-revisions.**

### Pass 1 — cross-cutting core (`app.py`, `db.py`, `tx.py`, `response.py`, `middleware.py`, `shape.py`, `lookup.py`, `errors.py`, `routes/clock.py`) vs PRD §2/§5
103,919 -> 110,077 chars (+6,158). 11 ambiguity-pins, 4 mismatch-revisions, ~90 behaviors verified already-pinned.

Mismatches: §2.11 tier 10 ordering (impl checks terminal BEFORE invalid-state, so a terminal resource always yields `ERR_ALREADY_TERMINAL` — `lookup.py:68-74`); §2.4 version semantics (one increment + one `updated_at` per row **per mutating request** however many cascade hops touch it, all rows sharing an identical `updated_at`, net-unchanged rows getting neither — `tx.py:34-64`); §2.4 clock split (`created_at`/`updated_at`/`api_request_timestamp` come from the **host wall clock**, only date arithmetic and business stamps from the logical clock — `db.py:83-89`); §2.5 percentage precision (impl validates the closed interval `[0,1]` only and accepts finer precision verbatim — `shape.py:153-162`).

Ambiguity pins: empty/whitespace `X-User-ID` -> `ERR_UNAUTHENTICATED`, exact untrimmed case-sensitive role match (`middleware.py:32-38`); `api_request_id` = `req_` + 20 chars of `A-Z0-9`, minted for errors too (`db.py:188-190`); resources serialised post-commit so returned `version`/`updated_at` are post-mutation (`response.py:19-27`); the four pagination `meta` keys **absent** not null on single-object and error responses (`response.py:9-16`); `limit`/`offset` accepted only as optionally-signed decimal-digit text, `10.0` rejected (`shape.py:205-212`); strictly-increasing `created_at` giving a total order with no ties (`db.py:83-89`); `offset >= total_count` -> empty `data` not an error, non-pagination filters exact-equality with out-of-vocabulary values matching nothing (`response.py:43`, `shape.py:229-262`); `id` = canonical lowercase 36-char UUIDv4 (`db.py:170`); full-request rollback atomicity (`app.py:55-71`); `current_utc` required ISO-8601 with offsets converted and naive read as UTC, unbounded in direction (`routes/clock.py:18`); SoD as exact string equality that **passes vacuously on a null anchor** (`middleware.py:63-66`); tier-3 shape semantics — JSON `null` counts as absent, integers reject booleans and `10.0` (`shape.py:40,62-69`); the clock endpoint's 200 + single `current_utc` field; unrouted path/undeclared method -> `ERR_INVALID_REQUEST` envelope with the transport's own status (`app.py:60-66`).

Already-pinned highlights: all **56** §5 error/HTTP-status rows programmatically diffed against `errors.py:12-78` with zero discrepancies; §2.10's ten path-segment 404 identifiers matching `lookup.py:7-18`; the full 14-tier ladder executing in the declared order; §2.3 defaults/bounds (limit 10/1/100) matching `shape.py:199-226`; the `2026-08-01T00:00:00Z` startup default.

### Pass 2 — `routes/agencies.py`, `routes/state_programs.py`, `routes/cpl.py`, `routes/policy_files.py` (+ their `calc.py`/`derive.py` callees) vs PRD §3.1–§3.4
110,077 -> 115,839 chars (+5,762). 16 ambiguity-pins, 10 mismatch-revisions, ~90 already-pinned across 22 endpoints.

Mismatches: financial re-filing's only state guard is the `TERMINATED` check, so re-filing over an undecided `SUBMITTED` review is accepted and overwrites the staged figures (`routes/agencies.py:123-130`); **both** financial decisions require `financial_review_status == SUBMITTED` — the PRD's "a `DEFICIENT` decision carries no preconditions at all" was wrong (`routes/agencies.py:146`); the "two-letter `state_code`" is not enforced at all (any JSON string, stored verbatim, byte-for-byte uniqueness — `routes/state_programs.py:30,39-41`); both `verified_*` fields are **optional**, a `VERIFY` missing `verified_expires_on` yielding `ERR_LICENSE_EXPIRED` not `ERR_INVALID_REQUEST`, and renewal overwriting the license number only when supplied (`routes/state_programs.py:129-150`); the four CPL issuance preconditions evaluate posture -> E&O -> appointment -> `cpl_permitted`, contradicting the PRD's stated order, and scope/state-cap are **not** re-tested at issuance (`routes/cpl.py:166-173`); the transfer-exception `note` is validated then discarded, not "persisted in the audit trail" (`routes/policy_files.py:235`); the §4 CPL-list row and §2.3 typed-filter list both omitted `complex_title_flag` (`routes/cpl.py:136`).

Ambiguity pins: the four `submitted_*` staging fields' initial 0/0/0/null; all four financial-package fields required with non-negative cents and a `YYYY-MM-DD` expiry; E&O minimum evaluated before net-worth so failing both gives `ERR_EO_LIMIT_BELOW_MINIMUM`; `note`/`reason`/`rationale` string-validated but **never persisted** at four separate sites; `transferee_agency_id` existence-resolved on any decision but eligibility-tested and persisted only on `TERMINATE`; suspend-driven account restriction keyed to **entry** into `FROZEN` so suspending an already-frozen agency restricts nothing further (`derive.py:245-249`); `cpl_permitted` a required boolean with no default; appointment creation imposing no agency precondition and not testing `license_expires_on`; a decline moving no agency field so advancing neither `Agency.version` nor `updated_at`; optional `void_reason` leaving null rather than refusing the void; no transition-role restriction out of `DECLINED`/`VOIDED` so either role gets `ERR_ALREADY_TERMINAL`; `cpl_id` existence-checked only with no same-agency/same-program consistency test; `issuance_elapsed_days` **signed**, a future `closing_date` giving a negative count and landing on `ISSUED`; `ISSUED` the only nameable target out of `PENDING` (naming `LATE_ISSUED` gives `ERR_INVALID_STATE`) and neither issuance state terminal.

Already-pinned highlights: the CPL referral ladder and labels (`calc.py:188-200`); the four floored coverage caps and their `min` incl. the non-`OPEN` halving (`calc.py:203-212`); the seven issuance guards in exact PRD order incl. priority conflict P2 and the agency-scoped duplicate-number reservation; the authority limit lifted by a non-null `referral_decided_by_user_id`; the posture formula with strict `>` on 50,000,000 (`calc.py:165-182`); reinstatement barred by `DEFALCATION_RISK` or any open critical finding; both conserved ledgers recomputed from rows never by delta (`derive.py:83-98`); transferee eligibility re-tested at transfer time.

### Pass 3 — `routes/remittance.py`, `routes/escrow.py`, `routes/claims.py` (+ all their `calc.py`/`derive.py` callees, cascades and ledgers) vs PRD §3.5–§3.9
115,839 -> 125,011 chars (+9,172). 24 ambiguity-pins, 7 mismatch-revisions, ~90 of ~120 behaviors already-pinned.

Mismatches: §2.1's transition-role list claimed narrowing for statement reopen and audit closure the impl does not have — reopen out of `DRAFT` is unnarrowed and closure is guarded by SoD-1 rather than a role name (`routes/remittance.py:30-36`, `routes/escrow.py:37-44`); finding creation is refused against a `DRAFT` audit too, not only a closed one (`routes/escrow.py:210-212`); disposition recomputes `critical_finding_count` and `risk_tier` as well as `open_finding_count` (`derive.py:59-77`); account restriction on escalation requires **entry** into `FROZEN` (`derive.py:245-249`); CASCADE-A hops 4–5 are conditioned on the posture **being** `FROZEN` rather than on entry, and hops 2–5 do not run when the rescore stays below 60 with no other freeze condition (`derive.py:267-272`); "live E&O coverage" on a claim is **only** the `eo_policy_limit_cents > 0` test — `eo_expires_on` is never consulted — and it runs after the state guard (`routes/claims.py:140-143`); the defalcation recourse tail fires on the posture **being** `FROZEN`, declines carry `SYSTEM` in ascending `created_at` order, and `defalcation_score` is deliberately not recomputed, so standing can sit at `DEFALCATION_RISK` above a sub-60 score until the next rescore (`routes/claims.py:157-166`, `derive.py:230-261`).

Ambiguity pins: a line may be added to a `SUBMITTED`/`RECONCILED`/`SETTLED` statement with no status precondition, and the three split totals are refreshed at line creation, submission **and** reconciliation so a post-submission line is inside the variance and the settlement identity (`routes/remittance.py:42-52,164-208,273,284`); `unreported_policy_count` mirrored from the `RECONCILED` statement latest by `(reconciled_at, creation order)` (`derive.py:113-124`); neither reopen path role-narrowed nor clearing `settled_amount_cents`, and the `RECONCILED`->`DRAFT` reopen deliberately leaving `submitted_at`/`reconciled_at` standing (`routes/remittance.py:352-380`); account registration not posture-gated; all seven snapshot inputs required with six non-negative and **no** cross-field relationship enforced (a negative adjusted balance is accepted), answering **200 OK** with the account row (`routes/escrow.py:128-156`); audit creation resolving `agency_id`/`follow_up_of_audit_id` for existence only with no owner-consistency test; the creation-time rescore able to freeze and restrict but never declining a letter nor spawning a successor; the snapshot check preceding the closed-account check on submission; the governing tolerance falling back to **0** when the agency holds no `ACTIVE` appointment (`derive.py:45-53`); auto-findings evaluated variance-first with a server-composed `narrative`; a findings-free audit satisfying clean closure vacuously; `is_repeat` ignoring the predecessor's own `status`; optional `cleared_amount_cents`/`disposition_note` each overwriting only when supplied and being ignored on the other branch, with neither outcome testing the parent audit's `status`; `notice_date` never compared with the closing date, periods or clock; absorption leaving the score untouched and carrying no punitive tail on a defalcation cause; `recovered_amount_cents` a non-negative integer with 0 accepted; neither resolution rewriting `decided_by_user_id`; and a §3.3 back-reference noting the §3.8 defalcation tail joins CASCADE-A/CASCADE-B as a `SYSTEM`-declining path (a gap invisible to pass 2, which owned §3.3).

Already-pinned highlights: the per-line premium split with retention rounded half-up and the share by subtraction (`calc.py:237-241`); the two-component late fee with its strict 15-day comparison; the settlement amount identity; CASCADE-C hop 5's release condition; the period-overlap rule; both three-way variance methods and the worked example (`calc.py:96-103`); the `base_severity` thresholds; both defalcation-score variants' scoping (`derive.py:169-210`); the inclusive 90-day audit spacing and surprise exclusivity; the full claim waterfall with tier-boundary inclusivity and the cap-before-cause-factor ordering (`calc.py:253-269`); the recovery ceiling; the three-part `ERR_CLAIM_POLICY_MISMATCH`.

### Whole-document integrity check (pass 3's closing duty, plus independent orchestrator re-verification)
- §4 endpoint table: **45 rows**; method+path set diffs empty against the 45 routes in `implementation/routes/`.
- §5 error table: **56** `ERR_` rows, no duplicates; id set diffs empty against the 56 ids in `implementation/errors.py`.
- All sections present and in order: §1, §2.1–§2.11 (11 subsections), §3.1–§3.9 (9 subsections), §4, §5 — none dropped by any pass. Orchestrator re-count: 5 `##` sections, 20 `###` subsections, 56 error rows.
- Document ends at a real boundary — the final `ERR_RECOVERY_EXCEEDS_RECOURSE | 422 Unprocessable Entity` row of the §5 table.
- md5 `PRD_FINALIZED.md` = `875be181522798d2527ab42745865452`, `PRD_COMPLETED.md` = `7ff0868bc205fef4ac986291fe69dd9c` — **not byte-identical**, confirming the scan genuinely ran (the known silent-no-op failure mode did not occur).

## PIPELINE COMPLETE
All nine steps finished. Final state: 116/116 tests passing in all 8 sweep rounds; `workspace/PRD_COMPLETED.md` written.
