# Worklog — task_2438_nursing_licensure_discipline

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2438_nursing_licensure_discipline` and `.../workspace` (index pre-assigned by orchestrator invocation; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T18:18:00.000Z

All three scaffold artifacts for `task_2438_nursing_licensure_discipline` are complete and the linter is clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2438_nursing_licensure_discipline/SCAFFOLD.yaml` (§1.0–§1.7, 3403 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2438_nursing_licensure_discipline/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 1832 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2438_nursing_licensure_discipline/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 4652 lines)

## Counts
- **SCAFFOLD.yaml**: 12 entities, 9 state machines (parallel shape: License carries independent `license_status` / `encumbrance_status` / `multistate_privilege_status` dimensions), 2 §1.2.1 concurrency rules, 8 calculations, 36 ordered validations, 67 endpoints, 47 error codes, 6 roles. `api_prefix: ""`, logical clock default `2026-08-01T00:00:00Z`, `difficulty_level: expert_plus`, complexity layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers, role model = segregation_of_duties.
- **§1.8**: 18 instances, exactly 2 per each of the nine §0.5 difficulty rules.
- **§1.9**: 95 instances across all nine claim-extraction-guide sections (entities 14, state_machines 14, calculations 13, validations 30, endpoints 6, errors 5, rbac 6, complexity_layers 6, consistency_model 1); 72 with full `test_recipe`, 23 `excluded_because:` stubs. Claim types are drawn only from the guide's per-section tables.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1111

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications
1. **Two SCAFFOLD.yaml reachability fixes.** Writing §1.9 exposed two validations that were permanently shadowed by the priority-10 state check. (a) `ERR_DEFICIENCY_LIMIT_REACHED` (priority 25): the original auto-DENY at `deficiency_cycle_count == 3` made the row terminal, so priority 10 always answered first — removed the auto-transition so the application freezes in DEFICIENT and both further-deficiency and resubmission return the budget error, leaving withdrawal as the only exit. (b) `ERR_LICENSE_ALREADY_ISSUED` (priority 33): redefined with a second, reachable clause (one live credential per `credential_type` per nurse per board) plus a `note:` documenting that the original clause is shadowed by the terminal ISSUED state; §1.6 catalog condition updated to match.
2. **`ERR_AUDIT_DOCS_NOT_SUBMITTED` (31)** resolved without a scaffold change: only the second conjunct is reachable — answer the doc request with `practice_hour_periods: []` so `audit_status` is legally `DOCS_SUBMITTED` but there is nothing to compute over.
3. **OCC coverage supplied by §1.9.** §1.8 only ever asserts `ERR_STALE_VERSION` negatively, so §1.9 carries a real stale-version test for each declared §1.2.1 rule (`renewal-create-stale-license`, `proceeding-open-stale-complaint`) plus a version-increment-per-write instance. The proceeding case doubles as a priority-9-beats-priority-10 proof.
4. **Three stubs converted to real instances.** An audit of "is every code positively triggered" showed `ERR_RENEWAL_FEE_UNPAID`, `ERR_CUSTODIAN_NOT_LINKED` and `ERR_CONTINUANCE_LIMIT_REACHED` appear in §1.8 only as negative (`!=`) assertions, so the stubs citing them were unsupported; they were replaced with full recipes (unpaid submit → 402; `EMPLOYER_PERSONNEL` demand on an unlisted custodian, which deliberately sidesteps the priority-13 PHI gate; and a fourth CONTINUE after the shared three-continuance budget is spent). All 47 error codes now have a positive trigger.
5. **Grounds style normalized** to `endpoints.<METHOD> <path>` across both design files (10 underscore-form references fixed), and `entities.License.fields.version` — a common field, not a declared one — re-grounded on the concurrency rule.
6. Verified independently of the linter: all `grounds:` resolve to declared §1.1–§1.7 elements, all stub citations name a real §1.8 instance, no stub carries a `test_recipe`, and all 113 instance names are unique across the union of both design files.

The hard constraint was honored throughout: no sibling `tasks/task_*/` directory was listed, globbed, grepped, or read.

## Step 3: Copy shared files — 2026-09-02T18:18:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2438_nursing_licensure_discipline/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T18:36:00.000Z

PRD generation is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2438_nursing_licensure_discipline/workspace/PRD.md`

**Truncation guard:** final line count **509**. The file ends at a real section boundary — the last section is `## 5. Error Code Catalogue`, whose final table row is `| ERR_PRACTICE_HOURS_INSUFFICIENT | 422 Unprocessable Entity |`. No trailing audit footer, no mid-sentence or mid-table cut. Structure: `# Nursing Licensure & Discipline API — Product Requirements Document`, `## 1. Introduction` (L3), `## 2. Global Specifications & System-Wide Principles` (L11, twelve subsections 2.1–2.12), `## 3. Business Logic & Workflows` (L217, nine subsections 3.1–3.9), `## 4. API Endpoint Definitions` (L385), `## 5. Error Code Catalogue` (L459).

**Hard Contract 1 — Field-Name Coverage: PASS.** Required inventory built programmatically from the scaffold: 145 `entities[].fields[].name` plus every endpoint request-body / query-param / path-param identifier, de-duplicated to **163 distinct required identifiers**. Backtick-token extraction over the PRD (code fences stripped so the `2.2` JSON block does not skew pairing) yields **0 missing**. This includes the 15 input-only names (`current_utc`, `decision`, `disposition`, `event_type`, `expected_complaint_version`, `expected_license_version`, `missed_screens`, `new_hearing_date`, `note`, `outcome`, `proposed_sanction_tier`, `reason_note`, `target_complaint_id`, `to_status`, `variant`), plus `limit`/`offset` and the `{id}` path parameter.

**Hard Contract 2 — Rule Coverage: PASS.**
- All **47** error IDs appear in the §1–§3 prose, not only in the §5 table (verified by set difference against the prose slice).
- All **57** distinct state values across the **9** state machines (initial, terminal, and every transition endpoint) appear verbatim; both parallel-dimension pairs (License `license_status` × `encumbrance_status`, RenewalApplication `renewal_status` × `audit_status`) are enumerated with terminal states called out.
- All **36** validations are ordered as an explicit 36-item priority ladder in §2.11; every scaffold `error_id` maps to its numbered rung (priorities 3 and 4 defer to "that family's not-found code", and all twelve 404 codes are individually named with their families in §2.10). The three ordering conflicts the scaffold flags are stated explicitly: 13 before 14 → `ERR_PHI_AUTHORIZATION_REQUIRED`; 18 before 28 → `ERR_NOTICE_PERIOD_NOT_MET`; 11 before 35 → `ERR_LICENSE_NOT_RENEWABLE`.
- All **8** calculations are reconstructible in prose: `ce_hour_credit_total` (§3.4, both variants + per-record quarter-hour quantisation before summing), `multistate_privilege_determination` (§3.3, full guard chain + both residency variants + evidence-priority ranking and tie-breaks), `sanction_severity_floor` and `panel_vote_tally` (§3.8, including the pinned top-down ladder walk and basis-point cross-multiplication), `audit_sample_selection` and `practice_hour_attainment` (§3.5, including per-period flooring before summing), `renewal_fee_assessment` (§3.4), `license_encumbrance_reconciliation` (§2.7).
- Both OCC rules, all `applies_to` scopes, field-level defaults (all 25 board-config fields), sibling-branch symmetry (both `BREACHED` edges, both `RESTRICTED` edges, both `VOID` edges), and the cross-entity cascades are covered.
- No pseudocode, no symbolic operators (`==`, `->`, `>=`, `ceil(`, `round_half_up`, `IN {`) and no fuzzy quantifiers survive anywhere in the document.

**Hard Contract 3 — §3 Path Purity: PASS.** 366 distinct backtick tokens in §3; **0 violations** — none starts with `/`, none is a bare HTTP method, none combines method+path.

**Table conformance:** §4 is exactly 4 columns with **67** rows, one per scaffold endpoint (set difference against the scaffold is empty in both directions) and **0 role-list mismatches**. §5 is exactly 2 columns with **47** rows in scaffold order, **0 ID or status mismatches**.

**Isolation constraint honored:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point.

**Orchestrator-side truncation re-verification:** independently confirmed 509 lines, final section `## 5. Error Code Catalogue` ending on a complete table row. No regeneration needed.

## Step 6: Generate implementation — 2026-09-02T19:10:00.000Z

Implementation complete and verified.

## Files written

All under `workspace/implementation/` (3,257 lines of Python, flat module layout — no packages, so imports work from any cwd):
`app.py` (Flask factory, blueprint registration, error handlers, global request lock, `app.run(host="0.0.0.0", port=$PORT, threaded=True)`); `store.py` (in-memory `Store` — 12 dicts + `RLock` + logical clock + license sequence, `new_id()`, `base_fields()`); `errors.py` (43-code `ERROR_CATALOG` + 3 infra codes, `ApiError`, `fail()`); `envelope.py` (`meta`/`data`/`response_type` envelope, `req_<20 uppercase alnum>` ids, logical-clock timestamps, per-request version-bump dedupe); `guards.py` (auth/RBAC, id resolution for all 12 families, ownership, body/type/enum/range validators, pagination, filtering); `timeutil.py` (ISO parse/format with 3 fractional digits + `Z`, month/day arithmetic with day clamping, whole-day differencing); `calc.py` (the 8 declared calculations — CE credit, multistate privilege, sanction floor, vote tally, audit risk + quota, practice-hour attainment, fee assessment, encumbrance reconciliation — `Decimal`/`ROUND_HALF_UP`, integer cents, basis-point cross-multiplication); `domain.py` (shared side effects: report queueing, privilege re-runs, licence/nurse reconciliation, renewability gates, the three clock sweeps); `routes_core.py` / `routes_licensing.py` / `routes_renewal.py` / `routes_enforcement.py` (the endpoints); `requirements.txt`, `start.sh` (`Flask>=3.0`; guarded `pip install` then `exec python3 app.py`, executable, binds `0.0.0.0`, `PORT` default 10000).

**67 endpoints** implemented — exactly matching PRD §4 (verified by enumerating `app.url_map`).

Storage is in-memory dicts only (grep confirms no sqlite/file writes); nothing is seeded — a fresh boot returns `total_count: 0` on every collection.

## Verification

`bash start.sh` booted on free high ports and served correctly. Three end-to-end smoke walkthroughs passed against fresh processes:
1. Examination licensure → multistate privilege → renewal (OCC, fee, CE, verification) → audit sampling/doc cycle/decision → RENEWED (expiry advanced 24 months) → complaint → evidence → referral → proceeding → convene → votes → SUSPENSION order (licence `SUSPENDED`/`PRIVILEGE_REVOKED`, nurse `ENCUMBERED`, `prior_discipline_count` 1, NPDB + one INTERSTATE_COMPACT report).
2. Disqualifying screening → board review → ATD path: monitoring agreement, period-conflict rejection, ownership rejection, execution, missed-screen suspension, recovery, completion → complaint `CLOSED`, licence back to `CLEAR`; clock sweep drove `ACTIVE→EXPIRED→LAPSED` with `NOT_ELIGIBLE`.
3. Endorsement + APRN base-licence chain, deficiency budget exhaustion, complaint consolidation with allegation-code merge, CONTINUE/REOPEN, REPRIMAND order queuing **no** reports.

All servers were killed; `__pycache__` removed.

## PRD ambiguities resolved (PRD taken as authoritative over SCAFFOLD.yaml)

- **PHI authorisation** required for both `PATIENT_CHART` and `PHARMACY_DISPENSING` (PRD §3.6), gated on `board.phi_authorization_required`.
- **Disposition** permitted from `INVESTIGATION_OPEN` *or* `EVIDENCE_COMPLETE`, stamping a `disposition_at` field the PRD names but the scaffold entity omits. Scaffold's input enum (`DISMISS`/`OFFER_ATD`/`REFER_TO_PROCEEDING`) kept.
- **Consolidation target** must be non-self, same `license_id`, not already consolidated, and in {RECEIVED, TRIAGED, INVESTIGATION_OPEN, EVIDENCE_COMPLETE}. Missing target on `DUPLICATE` → `ERR_CONSOLIDATION_TARGET_INVALID`; present-but-unresolvable → `ERR_COMPLAINT_NOT_FOUND` (id resolution is ladder step 4, before enum validation).
- **APRN base licence**: presence-only check at submit (`ERR_BASE_LICENSE_REQUIRED`); the full RN/LPN + ACTIVE + CLEAR + same-nurse check runs at qualification-verification.
- **Duplicate issuance**: PRD numbers `ERR_LICENSE_ALREADY_ISSUED` as ladder step 33, so the step-10 `ERR_INVALID_STATE` fires first when re-issuing from an already-`ISSUED` application; the "already issued" code surfaces on the live-credential-per-type-per-board clause.
- **Order-time reporting**: one NPDB report (`NURSE_AIDE_REGISTRY` for nurse-aide credentials) per credential the order encumbers, `basis_code` = adopted tier, plus exactly one `INTERSTATE_COMPACT`/`PRIVILEGE_LOSS` report. REPRIMAND and FINE queue neither.
- **`privilege_basis_state`** written only when the guard chain falls through to primary-state-of-residence resolution, else null; `privilege_variant` always records the variant that ran. A notification report on privilege determination is queued only from the on-demand endpoint and only on `MULTISTATE`.
- **Renewal supersede vs. lapse withdrawal**: creating a renewal withdraws sibling `DRAFT`/`SUBMITTED` renewals *with* refund into `Nurse.fee_credit_cents`; the clock lapse sweep withdraws `DRAFT`/`SUBMITTED`/`CE_DEFICIENT`/`CE_VERIFIED` renewals with *no* refund.
- **Payment** applies `fee_credit_cents` first, sets `fee_paid_cents = fee_applied_cents`, and increases `fee_paid_total_cents` by the full assessed fee; allowed from any non-terminal `renewal_status`.
- **Finalization**: `RENEWED` with audit `SELECTED`/`DOCS_REQUESTED`/`DOCS_SUBMITTED` → `ERR_INVALID_STATE`, with `FAILED` → `ERR_PRACTICE_HOURS_INSUFFICIENT`; `DENIED` on a failed audit opens a system `BOARD_INITIATED`/`FRAUD` complaint carrying de-duplicated employer names.
- **Proceeding lifecycle**: `sanction_floor_tier` and `adopted_sanction_tier` both initialise to `"NONE"` (index 0); CONVENE recomputes recusals *then* tests quorum against the recomputed panel and re-freezes the floor; CONTINUE resets `noticed_at` to the clock; REOPEN clears votes and resets the adopted tier; CONTINUE and REOPEN share one budget of 3. The presiding member is excluded from `seated_member_user_ids`. Votes accept the six tiers plus `NONE` (tier index 0, i.e. an abstention from every threshold); guard order is presiding-member then seated/conflict.
- **Nurse status**: `REVOKED` when credentials exist and all are `REVOKED`; else `ENCUMBERED` if any credential is `RESTRICTED`/`SUSPENDED`/`REVOKED` **or** any open complaint remains (`INVESTIGATION_PENDING` alone does not encumber the nurse); else `ACTIVE`.
- **Monitoring conflicts**: closed-interval intersection, plus the gap rule applied only in the stated direction (a *prior* agreement's `end_date` + `monitoring_clearance_gap_days`), across statuses {OFFERED, EXECUTED, ACTIVE, SUSPENDED_PENDING_REVIEW, COMPLETED, BREACHED}. The gap comes from the complaint's credential's issuing board (falling back to the nurse's home board).
- **Custodian hold capacity**: half-open overlap over {REQUESTED, PRODUCED} holds for that custodian across all complaints; refused at `>= max_concurrent_custodian_holds`.
- **Enum handling**: undeclared *values* → 400 `ERR_INVALID_REQUEST`; declared values that are not reachable *transitions* → 409 `ERR_INVALID_STATE` (e.g. `verification_status: UNVERIFIED`, `to_status: EXPIRED`/`LAPSED`, report `to_status: QUEUED`).
- **ARCHIVED board** blocks `POST /license-applications`, its submit, and `POST /renewal-applications` with `ERR_INVALID_STATE`.
- `GET /state-board-configs/{id}/nurses` filters on `home_board_config_id`. `audit-doc-request` clears `practice_hour_periods`. Version bumps are deduped per record per request, and records created in a request stay at version 1.

## Step 5: Generate unit tests — 2026-09-02T20:35:00.000Z

All generation is complete. Final state of the two deliverable directories:

## Files written

**`test_helpers/`** (9 modules, 2774 lines) — `types.py`, `api_client.py` (69 methods, all root-mounted), `api_errors.py` (43 codes + HTTP map registered with the framework), `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py` (1021 lines of seeders), `__init__.py` barrel. Final addition this session: `seed_sibling_license(api, ctx, **nurse_overrides)` (a second nurse + credential at the same board, needed because one live credential per type per nurse per board is the rule).

**`test_suite/`** (conftest + 20 test modules, **108 tests**): counts per file are 6/2/4/2/4/4/2/4/4/4 for `test_01`–`test_10`, then 14 (`test_11` entities), 12 (`test_12` state machines), 6 (`test_13` calculations), 11 (`test_14` validations 1-11), 11 (`test_15` validations 12-22), 6 (`test_16` endpoints), 2 (`test_17` errors), 6 (`test_18` rbac), 3 (`test_19` complexity layers), 1 (`test_20` consistency model).

## Coverage audit

| queue | instances | non-stub | translated | tests |
|---|---|---|---|---|
| A (Difficulty §1.8) | 18 | 18 | 18 (2 each) | 36 |
| B (Corner §1.9) | 95 | 72 | 72 (1 each) | 72 |

Mechanically verified: 108 `Design:` tags, every tag resolves to a real non-stub instance, no orphan tags, no stub tagged, no instance under-covered, no instance skipped. The 23 `excluded_because:` corner stubs are deliberately not translated. `pytest --collect-only` collects 108 tests with no errors; every `ApiErrorId` member and `ApiClient` method referenced exists; no unused `test_helpers` imports; no `skip`/`xfail`; no scaffold vocabulary anywhere in either directory; every `PRD §N: "..."` citation verified verbatim against `workspace/PRD.md`.

## Deviations from recipe wording (PRD-first, all deliberate)

1. **`calculations/renewal_fee_walks_the_on_time_tier_one_tier_two_and_reinstatement_buckets`** — the recipe's third bucket (late 61 days → 37000 reinstatement) is unreachable: §2.11 item 11 and §3.4 refuse any assessment past `expires_on` + grace with `ERR_LICENSE_NOT_RENEWABLE`. Asserted 17000 at day 1, 24000 at day 31, and the refusal beyond grace.
2. **`validations/convening_with_only_two_seated_members…`** — recipe asserts `sanction_floor_tier` null after the refused convene; §3.8 says a new proceeding starts it at `NONE`. Asserted `"NONE"`.
3. **`rbac/monitoring_approver_voting_on_the_same_nurse…`** — recipe seats three members including the approver, but §3.8 recuses the approver at creation, leaving quorum 2 so the convene the recipe requires could not happen. Seated four so quorum is 3 after the mandatory recusal; the asserted outcome (`ERR_VOTER_CONFLICT_OF_INTEREST`, `votes == []`, two clean ballots accepted) is unchanged.
4. **`validations/duplicate_triage_pointing_at_itself…`** — dropped one sub-assertion (a triage with no `target_complaint_id` at all returning `ERR_CONSOLIDATION_TARGET_INVALID`); ladder item 6 `ERR_INVALID_REQUEST` is equally derivable, so the PRD does not uniquely fix the outcome. The self-target assertion the instance is named for is fully covered.

Nothing under `workspace/implementation/` was read or written, and no sibling task directory was accessed.

(Orchestrator note: Steps 5 and 6 were launched as background subagents and ran concurrently; the impl generator finished first and never had visibility into `test_suite/`, preserving the intended isolation.)

## Step 7: Run tests and iterate — 2026-09-02T21:12:00.000Z

Clean sweep achieved. All 8 parallel rounds report 108/108.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 105/108 in every round with the same 3 deterministic failures. Sweep 2 (after fixes): 108/108 in all 8 rounds.

**Tests deleted:** none. All three failures traced to PRD-verbatim rules that the implementation got wrong.

**Fixes applied to `test_helpers/`:** none — every fixture/factory precondition matched PRD (`residency_evidence_entry`, `practice_hour_period` supply exactly the field shapes §3.1/§3.5 declare).

**Fixes applied to `implementation/`** (all in `workspace/implementation/`):

1. `routes_core.py` `_parse_residency_evidence` + `calc.py` `evidenced_primary_state` — the server was parsing each `residency_evidence` entry's `effective_date` into a datetime and re-serialising it as `...T00:00:00.000Z`, mutating the nurse's own declaration on echo. PRD §2.6 puts only the four system-managed timestamps in three-fractional-digit form; §3.1 gives the server no licence to rewrite a client-declared evidence entry. Now the raw string is stored verbatim and parsed on demand for the evidence ranking. (Fixed `test_variant_flip_writes_only_the_three_privilege_fields`.)

2. `routes_renewal.py` `audit_doc_submission` + `calc.py` `practice_hour_attainment` — same defect for `practice_hour_periods.start_on/end_on`, which §3.5 says are *overwritten wholesale* with the submitted array, not reformatted. Stored verbatim; the proration parses on demand. (Fixed `test_a_fourth_documentation_demand_is_refused_once_the_budget_is_spent`.)

3. `routes_licensing.py` `screening_result` — same verbatim-echo treatment applied to `screening_offense_records.disposition_date` (no test exercised it, but it was the identical PRD-fidelity defect); the lookback comparison now uses a parallel parsed list rather than the stored field.

4. `routes_licensing.py` `deficiency_application` — a fourth deficiency return on a frozen application reported `ERR_INVALID_STATE` because the generic origin-state check (§2.11 rung 10) ran before the budget check (rung 25). PRD §3.2 states specifically: "Once `deficiency_cycle_count` reaches 3 the application simply freezes in `DEFICIENT`, and from that point a further return and a resubmission are *both* refused with `ERR_DEFICIENCY_LIMIT_REACHED`." The budget check now pre-empts the state check for the `DEFICIENT`-and-spent case only; every other state still reports `ERR_INVALID_STATE`. (Fixed `test_the_third_deficiency_freezes_the_filing_and_leaves_only_withdrawal`.)

No endpoints, response fields, or side effects were added, and no startup seeding was introduced — storage remains in-memory only.

(Orchestrator verification: independently read all 8 `results.*.json` — each reports `passed: 108`, `total: 108`. Sweep artifacts confirmed present, per the known failure mode where a clean sweep is claimed without results files.)

## Step 8: Finalize PRD — 2026-09-02T21:24:00.000Z

Done. `PRD_FINALIZED.md` is written with five inline edits, all traced to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 509 lines; `PRD_FINALIZED.md`: 509 lines → **0.0% line delta** (every edit is an inline sentence added inside an existing paragraph or ladder item; no new sections, no reflow).

## Changes
- **§2.11 (rung 25)** — revise — appended that the deficiency-budget check is consulted ahead of check 10 for a further deficiency return on an application already frozen in `DEFICIENT` with its budget spent, and keeps its ladder place on every other path (explicitly including the resubmission path) — `routes_licensing.py:150-155` (vs. `routes_licensing.py:122-132` for the resubmit path).
- **§3.1 (residency evidence)** — insert — `residency_evidence[].effective_date` must be a parseable ISO 8601 instant but is stored/echoed as exactly the supplied string, never rewritten into the §2.6 three-fractional-digit form; consumers parse on demand — `routes_core.py:76-83`, `calc.py:126`.
- **§3.2 (deficiency cycles)** — insert — the frozen-and-spent return reports `ERR_DEFICIENCY_LIMIT_REACHED` although `DEFICIENT` is not a declared origin state; every other refused return (including on a `DEFICIENT` app with count < 3) still reports `ERR_INVALID_STATE` — `routes_licensing.py:150-153`.
- **§3.2 (screening result)** — insert — `screening_offense_records[].disposition_date` is echoed verbatim, unreformatted; the lookback comparison uses a parsed copy — `routes_licensing.py:210-236`.
- **§3.5 (documentation cycle)** — insert — `practice_hour_periods[].start_on/end_on` are kept as exactly the submitted strings by the wholesale overwrite; proration parses on demand — `routes_renewal.py:369-388`, `calc.py:300`.

## Per-edit pre-edit search log
1. **Rung-25 edit.** (a) Subject: precedence of `ERR_DEFICIENCY_LIMIT_REACHED` vs `ERR_INVALID_STATE`, and the general claim "budgets outrank state". (b) Enumerated: `grep DEFICIENCY_LIMIT` → only `routes_licensing.py:132` (submit/resubmit, after state + archived + program + APRN-base checks) and `:150/:155` (return); parallel budget rungs checked for a same-shaped exception — `routes_renewal.py:346-349` (audit doc-request budget runs *after* the state check) and `routes_enforcement.py:592-607` (continuance budget runs *after* the state check). (c) Adjustment: refused to phrase this as a general "budget pre-empts state" rule and named the single path (a further return on a frozen application); added "on every other path, including a resubmission of a frozen application, it keeps its place in the ladder" so the doc-request, continuance and resubmit orderings are not mis-described.
2. **§3.1 residency-evidence edit.** (a) Subject: stored/echoed representation of client-declared dates in `residency_evidence`. (b) Enumerated: `routes_core._parse_residency_evidence` (both writers: `create_nurse:272`, `patch_nurse:313`), `calc.evidenced_primary_state:118-136` (parses, skips unparseable and future entries, ranks by weight/date/index), `routes_licensing.privilege_summary:452`, `envelope.to_json:19-28` (strings pass through, `datetime` → `iso`). (c) Adjustment: scoped the sentence to `effective_date` only — the impl also drops unrecognised keys and re-emits only the three declared ones, so a broader "the entry is stored verbatim" claim would have been false; also worded the tie-break/ranking as "parses the stored string on demand" rather than restating the ranking (already PRD-verbatim).
3. **§3.2 deficiency-cycle edit.** (a) Subject: which error the deficiency endpoint reports per originating state. (b) Enumerated: `routes_licensing.deficiency_application:140-159` (body `reason_note` first → budget pre-empt → `status != SUBMITTED` → redundant budget), `submit_application:116-137`, `withdraw_application:279-289` (the "only remaining exit"). (c) Adjustment: added the explicit carve-out for `DEFICIENT` with count < 3 (which the impl still answers `ERR_INVALID_STATE`), and phrased the residual clause as "every other return the state machine refuses" so it makes no claim about which returns are refused — notably it does not imply an `ARCHIVED` board blocks a return, which this endpoint does not check.
4. **§3.2 screening-record edit.** (a) Subject: stored/echoed representation of `disposition_date`. (b) Enumerated: `routes_licensing.screening_result:205-252` (sole writer; parallel `disposed_at` list drives the comparison at `:232-236`), initialiser `:71`, `grep disposition_date` → no other reader; `envelope.to_json`. (c) No adjustment needed beyond scoping to `disposition_date`.
5. **§3.5 practice-hour-period edit.** (a) Subject: stored/echoed representation of `start_on`/`end_on` in submitted periods. (b) Enumerated: `routes_renewal.audit_doc_submission:357-396` (sole non-empty writer), `audit_doc_request:352` and `create_renewal:78` (both set `[]`), `calc.practice_hour_attainment:289-313` (parses on demand, skips unparseable), `audit_decision:403` (non-empty test), `finalize_renewal:259,269-271` (reads `employer_name` only). (c) Adjustment: deliberately restricted to `start_on`/`end_on` and did **not** say the period is stored verbatim — the impl coerces `hours` to an integer and requires a non-empty string `employer_name`, so a whole-entry claim would have introduced a new mismatch outside the Step 7 subject.

## Step 9: Complete PRD — 2026-09-02T21:56:00.000Z

Done. `PRD_COMPLETED.md` is written and the audit is closed.

## Measurements

| | source `PRD_FINALIZED.md` | `PRD_COMPLETED.md` |
|---|---|---|
| lines | 509 | 512 (+3, all three the new §5 table rows) |
| chars | 111,251 | 132,522 (**+21,271**) |

No new sections; every other change is an in-paragraph insert or revision.

## Counts
- **ambiguity-pins: 44**
- **mismatch-revisions: 12**
- 56 edited lines total

## Changes

- §2.1 — insert — ambiguity — a present-but-blank `X-User-ID` is `ERR_UNAUTHENTICATED`, not just an absent one — `guards.py:37`
- §2.1 — revise — **mismatch** — PRD claimed `Applicant` is never given a collection listing; impl gives them the per-renewal CE-claim listing, with ownership enforced on the parent before the page is built — `routes_renewal.py:171-181`
- §2.2 — insert — ambiguity — `api_request_id` shape: `req_` + 20 uppercase-alnum characters — `envelope.py:15`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the logical clock, never the wall clock; pre-set default `2026-08-01T00:00:00.000Z` — `envelope.py:31`
- §2.2 — insert — ambiguity — two-decimal quantities serialise as bare JSON numbers, so trailing zeroes of the stated scale are lost (`30.0`) — `envelope.py:19`
- §2.3 — insert — ambiguity — `created_at` ascending is stable for ties; declared filters are exact-equality and conjunctive; undeclared query params ignored — `guards.py:329,335`
- §2.4 — insert — ambiguity — clock instant is adopted verbatim and may move backwards; sweeps run expire-all → lapse-all → activate-agreements, each in `created_at` order, so one jump can both expire and lapse a credential — `routes_core.py:91`, `domain.py:163`
- §2.5 — insert — ambiguity — `practice_lookback_months` is stored and echoed but read by no calculation — `calc.py` (no reader)
- §2.5 — insert — ambiguity — board integer ranges enforced identically on create and amend: all ≥0, three `_bp` fields ≤10000, `ce_hours_required` >0 — `routes_core.py:19,121,158`
- §2.6 — insert — ambiguity — "every mutation" is per request, not per field write; created records stay at version 1; a failing request advances nothing — `envelope.py:44,50`
- §2.6 — insert — ambiguity — which client instants are echoed verbatim vs normalised to the canonical UTC rendering, and that parsing accepts `Z`, offsets, or naive-as-UTC — `timeutil.py:8`, `routes_core.py:83`
- §2.7 — insert — ambiguity — reconciliation's only side effect is re-running privilege, and only on the transition *to* `CLEAR` — `domain.py:82-101`
- §2.7 — insert — ambiguity — nurse aggregate status is a full recompute, three limbs tested last-to-first, no-credential nurse reads `ACTIVE` — `domain.py:103-125`
- §2.8 — revise — **mismatch** — dropped the false premise "only one non-terminal renewal may exist per credential" (supersession reaches only `DRAFT`/`SUBMITTED`) — `routes_renewal.py:60`
- §2.9 — insert — ambiguity — integer fields accept `7.0` and reject `7.5`; number fields take full precision; booleans and numeric strings rejected for both — `guards.py:163,194`
- §2.10 — insert — ambiguity — a wrong-shaped parent id (number/object) reports that family's not-found code, not a malformed-field error — `guards.py:65`
- §2.11 — revise — **mismatch** — step 10's board-`ARCHIVED` limb is scoped to three acts only (open application, submit/resubmit, create renewal); every other transition proceeds against an archived board — `routes_licensing.py:52,125`, `routes_renewal.py:46`
- §2.11 — insert — ambiguity — on a continuance the budget check precedes the `new_hearing_date` presence check — `routes_enforcement.py:564-600`
- §2.12 — revise — **mismatch** — the ledger identity is broken by the lapse sweep, which withdraws filings writing only `renewal_status`, granting no credit and leaving `fee_applied_cents` standing — `domain.py:163+`
- §3.1 — insert/revise — ambiguity — two further amendable board integers (`practice_lookback_months`, `renewal_period_months`) plus `board_name`; `state_code` silently ignored on amend; version advances even when nothing changed; `ARCHIVED` → `ACTIVE` allowed — `routes_core.py:145-173`
- §3.1 — insert — ambiguity — all six program inputs mandatory; `nclex_first_time_pass_rate_bp` unread; `program_code`/`degree_level`/`state_board_config_id` ignored on amend; empty amend still bumps version — `routes_core.py:203,241`
- §3.1 — insert — ambiguity — all five nurse inputs mandatory; `birth_year` only type-checked and `ssn_last4` only non-empty (no range, no 4-digit test) — `routes_core.py:262`
- §3.1 — insert — ambiguity — residency-evidence entries need all three keys, `state_code` exactly two uppercase letters, and are normalised to exactly those three keys — `routes_core.py:65-83`
- §3.2 — insert — ambiguity — of the four conditional field rules only "APRN requires `aprn_role`" is enforced at open; the rest are deferred or unpoliced — `routes_licensing.py:49`
- §3.2 — insert — ambiguity — submit checks run in a fixed order and a missing `education_program_id` is `ERR_INVALID_STATE`, not a malformed body — `routes_licensing.py:122-132`
- §3.2 — insert — ambiguity — `prior_license_verified` is written before every route check, so a failed verification still leaves the new flag standing while status/`updated_at`/`version` are untouched — `routes_licensing.py:167-173`
- §3.2 — revise — **mismatch** — PRD said a `PROBATION` program forces board review and writes an allegation-free complaint; impl treats the three postures interchangeably and creates nothing — `routes_licensing.py:179`
- §3.2 — insert/revise — ambiguity — `screening_offense_records` mandatory but may be empty, entries normalised to two keys, and the lookback is calendar-month subtraction with month-end clamping — `routes_licensing.py:210-232`
- §3.3 — insert — ambiguity — `license_number` format `STATE-TYPE-000001` from one process-wide sequence; `expires_on` uses clamped calendar months; issuance restamps the application's `decided_at` — `store.py:29`, `routes_licensing.py:327,342`
- §3.3 — insert — ambiguity — privilege reports only from the on-demand endpoint (`source_entity_type` `LICENSE`, kind `INITIAL`), and `variant` is mandatory there — `routes_licensing.py:421-431`
- §3.3 — revise — **mismatch** — `to_status` accepts all five enum members but `EXPIRED`/`LAPSED` are refused with `ERR_INVALID_STATE` rather than treated as malformed — `routes_licensing.py:412`
- §3.4 — insert — ambiguity — create-renewal field types: `attested_practice_hours` integer ≥0, `carry_over_hours_claimed` number ≥0, `expected_license_version` integer — `routes_renewal.py:37-39`
- §3.4 — revise — **mismatch** — supersession withdraws only `DRAFT`/`SUBMITTED` siblings (oldest first); a `CE_DEFICIENT` or `CE_VERIFIED` sibling coexists with the new filing — `routes_renewal.py:57-68`
- §3.4 — insert — ambiguity — fee assessment is permitted from any non-terminal state and is repeatable, each repeat re-adding the full fee to `fee_paid_total_cents` — `routes_renewal.py:111-134`
- §3.4 — insert — ambiguity — `minutes` must be a whole number; all four CE fields mandatory; verification has no origin gate and flips freely between `VERIFIED`/`REJECTED`, while `UNVERIFIED` is refused — `routes_renewal.py:147,425-434`
- §3.4 — revise — **mismatch** — PRD gated only the grant on `CE_VERIFIED`; impl requires it for denial too, and an audit merely in flight yields `ERR_INVALID_STATE` (not the insufficiency code); grants queue no report — `routes_renewal.py:236,244-247`
- §3.4 — insert — ambiguity — the denial-path fraud complaint: custodians deduped in first-appearance order, empty `allegation_codes`, `PENDING` finding, clock-stamped dates, null assignments — `routes_renewal.py:267-291`
- §3.5 — insert — ambiguity — doc-request `note` is accepted then discarded; all four period keys mandatory, `hours` a non-negative number truncated toward zero; the array may be empty — `routes_renewal.py:345,363-388`
- §3.6 — insert — ambiguity — four complaint fields mandatory, `incident_date` unconstrained against the clock; the two code arrays optional arrays of strings — `routes_enforcement.py:40-72`
- §3.6 — insert — ambiguity — `jurisdiction_finding` enum named and mandatory; an unresolvable `target_complaint_id` reports `ERR_COMPLAINT_NOT_FOUND` first; the merge bumps the target's version only when a code was actually added — `routes_enforcement.py:94-142`
- §3.6 — insert — ambiguity — four demand fields mandatory and the hold window strictly non-degenerate, validated before the investigation-state gate — `routes_enforcement.py:159-176`
- §3.6 — revise — **mismatch** — the PHI-authorisation requirement fires only when the credential's board has `phi_authorization_required` true (whitespace-only identifiers rejected); a board with the flag off takes unauthorised chart demands — `routes_enforcement.py:177-178`
- §3.6 — insert — ambiguity — `page_count` mandatory integer ≥0; demands listable per complaint filtered by `status`/`record_class`/`custodian_code` — `routes_enforcement.py:231,213`
- §3.6 — insert — ambiguity — `disposition` enum named and mandatory — `routes_enforcement.py:267`
- §3.7 — insert — ambiguity — agreement counters are integers ≥0, `required_negative_screens` unread by any rule, four fields mandatory, `start_date` ≤ `end_date` with a same-day period accepted — `routes_enforcement.py:317-372`
- §3.7 — insert — ambiguity — the reinstatement-gap board is the one that issued the originating complaint's credential, falling back to the nurse's `home_board_config_id`, then to 0 — `routes_enforcement.py:395-424`
- §3.7 — insert — ambiguity — `missed_screen_count` defaults to 1; the event `note` is validated then discarded; all four events require `ACTIVE`/`SUSPENDED_PENDING_REVIEW`, so an `EXECUTED` agreement accepts none — `routes_enforcement.py:426-494`
- §3.7 — revise — **mismatch** — breach's third link is a filter on the credential write, not a gate: a credential outside the listed states keeps its status while the breach and the remaining links still land; the nurse version bumps only on an actual change — `routes_enforcement.py:426-494`
- §3.8 — insert — ambiguity — `continuance_count` integer ≥0; four create fields mandatory; `seated_member_user_ids` may be empty, opening a panel that simply fails quorum — `routes_enforcement.py:496-546`
- §3.8 — insert — ambiguity — `new_hearing_date` is mandatory for the continuance alone and only checked after the state and budget checks — `routes_enforcement.py:564-600`
- §3.8 — revise — **mismatch** — closing requires an *effective ballot from a seated* member; votes from outside the seated set do not count, and a close with none is `ERR_INVALID_STATE` — `calc.py:222-233`
- §3.8 — insert — ambiguity — `proposed_sanction_tier` mandatory and may be the literal `NONE` (counted in the denominator, supporting no index); voting is accepted in any non-terminal proceeding state — `routes_enforcement.py:635-639`
- §3.8 — revise — **mismatch** — a probation order does **not** force `SINGLE_STATE`: the determination reads only *other* credentials' encumbrance, so the just-restricted credential can still read `MULTISTATE` — `calc.py:164-172`
- §3.8 — revise — **mismatch** — all three order cascades treat the stated permissions as filters on the `encumbrance_status` write, never gates on the order; the rest of each cascade lands regardless — `routes_enforcement.py:666-757`
- §3.8 — insert — ambiguity — order reports all carry the *proceeding's* id in `source_entity_id`, queued disciplined-credential-first then dependents by `created_at` then one interstate report; `REPRIMAND`/`FINE` queue nothing; proceedings listable per complaint by `status` — `routes_enforcement.py:666-757,303`
- §3.9 — insert — ambiguity — `QUEUED` is a legal `to_status` spelling but an unreachable target (`ERR_INVALID_STATE`); voiding stamps no instant; every transition bumps `version` — `routes_enforcement.py:781-805`
- §4 preamble — insert — ambiguity — body parsed as JSON regardless of `Content-Type`, absent/empty body read as `{}`, non-object body `ERR_INVALID_REQUEST`; unrouted path → `ERR_NOT_FOUND` 404, undeclared method → `ERR_METHOD_NOT_ALLOWED` 405 — `guards.py:110`, `app.py:49`
- §4 (`GET /state-board-configs/{id}/nurses` row) — revise — **mismatch** — the listing filters on `home_board_config_id`, not on declared primary state — `routes_core.py:188`
- §5 — insert — ambiguity — three framework codes that had no catalogue row: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `errors.py`, `app.py:49-62`

Only `PRD_COMPLETED.md` was modified; `PRD_FINALIZED.md`, `implementation/`, and the test trees are untouched. Tests were used only as a cross-reference, never as the alignment target.

---

## Pipeline complete — 2026-09-02T21:57:00.000Z

Steps 1–9 all executed. Final artifacts: SCAFFOLD.yaml + both design indices, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md, test_helpers/ (9 modules), test_suite/ (conftest + 20 modules, 108 tests), workspace/implementation/ (67 endpoints), and results.1–8.json all at 108/108.
