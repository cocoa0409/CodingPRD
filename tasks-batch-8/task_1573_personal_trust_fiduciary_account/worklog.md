# Worklog — task_1573_personal_trust_fiduciary_account

## Step 1: Create Task Directory — 2026-08-13T21:59:00.000Z

Task directory `tasks/task_1573_personal_trust_fiduciary_account/workspace` created by a prior run (RESUME). Directory exists; Step 1 treated as DONE per resume instructions.

## Step 2 (prior attempt): Generate Scaffold — killed mid-flight

Prior run produced `SCAFFOLD.yaml` (invalid YAML — flow-sequence parse error at line 737) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (invalid YAML — flow-mapping parse error at line 131); `SCAFFOLD_CORNER_DESIGN.yaml` was never written. Both partial artifacts are discarded; Step 2 re-run from scratch.

## Step 2: Generate Scaffold — 2026-08-13T23:46:16.000Z

All three artifacts are complete and validated. Final summary:

## Deliverables

| File | Lines | Status |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1573_personal_trust_fiduciary_account/SCAFFOLD.yaml` | 1153 | valid YAML (full overwrite of the truncated file) |
| `/home/ubuntu/github/CodingPRD/tasks/task_1573_personal_trust_fiduciary_account/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 727 | valid YAML (full overwrite) |
| `/home/ubuntu/github/CodingPRD/tasks/task_1573_personal_trust_fiduciary_account/SCAFFOLD_CORNER_DESIGN.yaml` | 1001 | valid YAML (created fresh) |

**Validation:** all three files parse cleanly with `yaml.safe_load`. `scaffold_lint.py` verdict, pasted verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(90 endpoints, 14 entities, 19 §1.8 instances, 44 §1.9 active instances + 7 `excluded_because` stubs, 684 recipe calls scanned.) A separate audit script additionally confirmed: zero unbound `${var}` placeholders, all instance names unique across both design files, all `grounds:` references resolve, no forbidden concurrency vocabulary, and every catalog error is referenced by a validation row or transition. All numeric asserts (fee tiers, waterfall lines, DNI/deduction, share reallocation, drift ratios) were pre-computed with a Python script and pinned as literals.

## Domain model overview

The scaffold models a bank trust department as a **flat topology of 14 entities** around `TrustAccount` (lifecycle DRAFT → UNDER_ACCEPTANCE_REVIEW → ACTIVE ⇄ SUSPENDED → TERMINATING → TERMINATED → CLOSED). `TrustDocument` is self-referential (version supersession with interpretation/approval); `Beneficiary` carries class shares in basis points with a conserved Σ=10000 invariant enforced at acceptance and restored after death via floor-plus-largest-remainder reallocation. `DistributionRequest` implements the committee workflow (cyclic UNDER_REVIEW ⇄ INFORMATION_REQUESTED loop, VOTING with quorum ≥3 auto-decision, reservation waterfall into income/principal buckets); `CommitteeVote` is append-only. `InvestmentPolicyStatement` uses half-open effective windows (abutment legal) while `FeeAssessment` FINAL periods must tile gap-free — the two contrasted interval semantics. `ComplianceReview` opens on unrounded-ratio band breaches (display value rounds separately — a pinned trap), with CRITICAL severity auto-suspending the trust (a 4-hop cascade). `LedgerEntry` is immutable and drives all derived balances; receipts split INCOME/PRINCIPAL per UPIA-style rules with rounding remainder to principal. `AnnualStatement` (DISPUTED→DRAFT regeneration cycle, 30-day objection window), `TaxReturnFiling` (TENTATIVE vs FINAL DNI dual variants, 65-day election, amendment cycle, preparer≠reviewer SoD), and `TerminationCase` (reserve → tax clearance → SoD final accounting → per-line-rounded waterfall distribution with delta-to-largest-share) complete the model. Two OCC rules guard request/holding creation on `TrustAccount.version`; seven roles implement segregation of duties. §1.8 covers all nine difficulty rules (19 instances, combinatorial formulas in modes a/b/c); §1.9 adds 44 breadth probes across all nine guide sections.

## Step 3: Copy Shared Files — 2026-08-13T23:47:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1573_personal_trust_fiduciary_account/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T00:07:00.000Z

All contracts verified. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1573_personal_trust_fiduciary_account/workspace/PRD.md` — 358 lines.

**Section list:**
- §1. Introduction (2 paragraphs: business context of bank trust departments, then system scope)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (7 roles; 5 opaque, `CommitteeMember`/`Beneficiary` entity-backed — each individually named)
  - 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, verified programmatically)
  - 2.3 Pagination (`limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, four meta fields)
  - 2.4 Common Resource Properties (UUID `id`, ISO-8601 3-fractional-digit timestamps, `version`; explicit note that CommitteeVote and LedgerEntry carry only `id` + `created_at`)
  - 2.5 Integer-Cent Accounting and Rounding Discipline
  - 2.6 The Append-Only Ledger and Derived Fiduciary Balances (incl. global statement-staleness rule)
  - 2.7 Optimistic Concurrency Control on Trust Accounts (both OCC write endpoints named, `expected_trust_account_version` + `ERR_STALE_VERSION` 412, pure stale-version framing)
  - 2.8 Validation Order and Error Precedence (all 11 priority groups in explicit order)
  - 2.9 Segregation of Duties and Beneficiary Objection Windows
  - 2.10 Resource Addressing and the Logical Clock (initial reading 2026-08-01T00:00:00Z)
- §3. Business Logic & Workflows (9 subsections): 3.1 Trust setup/documents/acceptance, 3.2 Beneficiaries/shares/committee, 3.3 Distributions (review → vote → disburse), 3.4 Investment policy/trading/drift, 3.5 Receipts & principal–income allocation, 3.6 Trustee fees, 3.7 Annual statements, 3.8 Form 1041 filings, 3.9 Termination & final waterfall
- §4. Endpoint Definitions (4-column table, 90 rows, verified 1:1 against scaffold)
- §5. Error Code Catalogue (2-column table, 36 rows, all HTTP codes verified)

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input/query_params: 129 required, 129 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 11 groups expressed as an explicit ordered list in §2.8, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + expected_trust_account_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 64 checked, all from/to state names present with preconditions and side effects in prose, 0 missing
- calculations[]: 9 checked, 9 fully expressed as operator-free prose (tiered fee, receipt split, balances, drift, quorum tally, share reallocation, DNI sequence, final waterfall, statement totals), 0 missing
- validations[] conditions: all matchable to error_ids in §2/§3 prose; all 36 error IDs appear in §1–§3, 0 missing
- endpoints[].side_effects / applies_to: all cascades expressed (terminate, mark-deceased, disburse, fee post/reverse, vote decision, IPS activate), 0 missing
- entities[].fields[] structured content: defaults, variants, and computed-field derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: withdraw (3 from-states), cancel (5), resolve (3), escalate (2) rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 367
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage notes:** All 44 state values, 93 enum literals, and 7 role names appear verbatim. Constants are embedded in business prose with unit conversions ($1M/$3M tier caps in cents, $1,250 minimum quarterly fee, $300 exemption, quorum of three, 10,000-basis-point class sum, 25% concentration cap, 30-day objection windows, Jan 1–Mar 6 election window). No pseudocode operators or fuzzy hedging words were detected outside code fences. One scaffold ambiguity resolved deliberately: the state-machine note saying suspension blocks holdings purchases conflicts with the holdings endpoint's explicit "ACTIVE or SUSPENDED (trading to cure a breach)" gate — the PRD follows the endpoint-level gate and states trading is the deliberate exemption from suspension.

## Step 5: Generate Unit Tests — 2026-08-14T00:30:00.000Z

All checks pass. Generation is complete and verified.

## Summary

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1573_personal_trust_fiduciary_account/`):

`test_helpers/` (Stage 1 — 9 files):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 24 status/field enums + 16 entity TypedDicts (CommitteeVote and LedgerEntry correctly omit `updated_at`/`version` per the PRD's common-fields rule)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~70 methods)
- `api_errors.py` — all 36 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + trust balance invariant checker
- `factories.py` — payload factories (input fields only)
- `constants.py` — fee tiers, min-fee floor, quorum, exemption, objection window
- `test_users.py` — 7 role header sets + per-instance builders for the two entity-backed roles
- `fixtures.py` — composite fixtures: state progression, funded-trust hierarchies, distribution lifecycle (review/voting/approved/disbursed), IPS/holdings, fee lifecycle with SoD-split users, termination gauntlet to FINAL_ACCOUNTING_APPROVED

`test_suite/` (Stage 2 — 14 files, 13 test files): `conftest.py` + `test_01_trust_shell.py` through `test_13_optimistic_concurrency.py`

**Test count: 121.**

**§1.8 (queue A — difficulty): 19/19 instances emitted, 0 skipped.** Every instance got exactly 2 tests (38 difficulty-tagged tests). No instance failed the PRD-first filter — the PRD verbatim-covers every indexed claim (dual fee/DNI variants, tiered fee math, waterfall per-line rounding, pinned DNI order, info-cycle and amendment loops, both cascades, both priority pairs, quorum/drift boundaries, both cross-entity gates, IPS adjacency vs fee tiling, reserve/share conservation).

**§1.9 (queue B — corner): 44/44 non-stub instances emitted, 0 skipped** (83 corner-tagged tests). The 7 `excluded_because:` stubs were not translated; each cross-reference was verified to resolve to a real difficulty instance that owns the assertion.

**Design-tag confirmation:** An automated audit confirmed every one of the 121 test docstrings ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line copied verbatim from the source YAMLs and resolving to a real instance — no untagged, dual-tagged, or dangling tags. A second sweep verified every PRD citation in every docstring contains a ≥8-word substring that literally greps PRD.md (whitespace-normalized). All files byte-compile and are pyflakes-clean.

One notable adjudication during generation: the compliance-review list endpoint declares no `asset_class` filter, so the FIXED_INCOME-absence assertion from `drift_exact_band_edge_vs_just_over` is done client-side over the full list rather than via an undeclared query parameter (which a faithful PRD-only implementer could ignore).

## Step 6: Generate Implementation — 2026-08-14T00:45:00.000Z

Implementation complete and verified. Summary:

## Files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_1573_personal_trust_fiduciary_account/workspace/implementation/`:

- `start.sh` — executable launcher (details below)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, envelope-shaped error handlers (ApiError, 404, 405, 500)
- `db.py` — in-memory dicts for all 14 entity types; **starts empty every boot, zero seeding** (verified: all list endpoints return `total_count: 0` on a fresh boot)
- `clock.py` — logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock); preserves the raw ISO string supplied to `/_clock/set_current_utc` so assigned timestamps match the set value verbatim
- `errors.py` — `ApiError` + all 36 error-ID constants from the catalog
- `response.py` — exact envelope: `meta{api_request_id, api_request_timestamp}` (+`limit/offset/total_count/has_more` on lists), `response_type`, `data`; error body `{error_id, message}`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (7 roles), role authorization
- `validation.py` — request-shape validation (priority 2): required fields, enums, positive ints, ISO dates/datetimes, `limit` 1..100, `offset` >= 0
- `serialize.py` — per-entity serializers; TrustAccount's 8 derived fields (balances, reservations, available, TMV, pending count) computed live from the ledger/requests/holdings
- `services/workflow.py` — entity minting (`id`/`created_at`/`updated_at`/`version`, lean variant for votes/ledger), `touch` version bumps, ledger append with the **global statement-staleness cascade** (DRAFT/FINALIZED → SUPERSEDED on any append in the fiscal-year window), fiscal windows, list plumbing (created_at ASC with stable insertion tiebreak)
- `services/calc.py` — all 8 calculations with `Decimal` + ROUND_HALF_UP at exactly the named steps: tiered trustee fee (PROVISIONAL vs FINAL as-of pricing via per-holding price history), UPIA receipt allocation (split rows, remainder to PRINCIPAL), IPS drift (unrounded ratio for decisions, 2-dp display, CRITICAL only for OVERWEIGHT beyond target+2·band per PRD, in-place review update, CRITICAL-create auto-suspends), committee quorum (3), largest-remainder share reallocation (created_at tiebreak, never id), pinned DNI sequence, final distribution waterfall (per-line rounding then delta to largest share), statement totals
- `routes/` — 13 blueprints: `clock_routes`, `trusts`, `documents`, `beneficiaries`, `committee` (members + votes), `distributions`, `investments` (IPS + holdings), `compliance`, `ledger`, `fees`, `statements`, `filings`, `termination`

## Key contract behaviors implemented

- Validation precedence per PRD §2.8 (auth → shape → role → ownership/SoD → existence → state/OCC → fiduciary gates → temporal → cross-entity → aggregate → funds-last)
- OCC `expected_trust_account_version` → `ERR_STALE_VERSION` (412) on the two guarded writes; path trust-id → `ERR_TRUST_NOT_FOUND`, all other missing ids → `ERR_RESOURCE_NOT_FOUND`
- All state machines incl. cyclic loops (info-request, fee dispute/recalculate, statement dispute/regenerate, amendment), segregation-of-duties pairs, 30-day inclusive objection windows, ledger immutability (`ERR_LEDGER_IMMUTABLE` 405), FINAL-fee tiling, one-statement-per-year, one-filing-per-year-ever, termination cascade and close gauntlet

## start.sh confirmation

Reads `$PORT` (default 10000 via `app.py`), binds `0.0.0.0` (verified reachable on the host's external interface), runs in the **foreground** via `exec python3 app.py`, and guards the dependency install with `if ! python3 -c "import flask"` so per-test reboots skip pip. Verified: two clean boots via `bash start.sh` (default port and `PORT=19001`), each with a pristine empty store.

Validated with 7 end-to-end suites (all passing against one fresh server): core CRUD/acceptance/distribution/disburse, investment drift/suspension/reinstate, mark-deceased reallocation, clock + objection windows + fee lifecycle, full termination waterfall with statement/tax close, error precedence/pagination/voting edge cases, and FINAL-fee as-of pricing/65-day election/suspension blocks.

## Step 7: Run Tests and Iterate — 2026-08-14T01:19:00.000Z

## Summary

**Exit state: all 8 parallel rounds pass — 120/120 tests in every round** (suite was 121 tests; 1 deleted per the PRD-First contract).

**Iterations run:** 2 full 8-round sweeps + 1 single-round isolated probe (used to separate true failures from shared-server pollution after the first batch of fixes).

**Root cause of 93/121 failures (rounds were perfectly consistent, 8/8):** the test fixtures accepted trusts without an APPROVED TrustDocument, which PRD §3.1 forbids verbatim ("at least one TrustDocument of the trust must be APPROVED, otherwise `ERR_DOCUMENT_NOT_APPROVED`"). The implementation was PRD-faithful; the test artifact was wrong.

**Tests deleted (1):**
- `test_06_distribution_cycles_cascades.py::TestErrorPrecedenceSafetyBeatsReferential::test_purpose_error_wins_over_cross_trust_error` — unique-derivability collapse: it asserted create-time purpose-standard precedence (scaffold rule `safety_beats_referential_on_request_create`), but PRD §3.3 assigns the purpose check to open-voting ("Opening the vote is the fiduciary hinge, and its preconditions are evaluated in the order given here… The `purpose_category` must be permitted…") while the create paragraph enumerates only `ERR_NOT_OWN_RESOURCE`/`ERR_CROSS_TRUST_REFERENCE`/`ERR_TRUST_NOT_ACTIVE`/`ERR_STALE_VERSION`. A PRD-only implementer returns `ERR_CROSS_TRUST_REFERENCE` at create, as the implementation does. Feedback for unit-test-generator: priority-pair instances must be placed at the endpoint where the PRD evaluates both checks.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `create_active_trust` and `setup_funded_trust`: flipped `with_document` default to `True` (acceptance requires an APPROVED document per PRD §3.1; 84 of 93 failures traced to this one fixture default).

**Fixes applied to `test_suite/`:**
- `test_12_termination.py` — import `make_officer_headers` from the `test_helpers` barrel instead of `test_helpers.fixtures` (ImportError broke collection of the entire suite in iteration 1).
- `test_02_security.py` (2 withdraw tests), `test_03_documents_acceptance.py` (2 version tests), `test_04_ledger_basics.py` (1 initial-states test), `test_06_distribution_cycles_cascades.py` (`_two_hems_trusts` + cross-trust test), `test_12_termination.py` (`_distributed_case`) — added `create_approved_document(...)` before submit/accept in every inline accept flow; version assertions unchanged (document lifecycle does not bump the trust version).
- `test_08_investments_compliance.py::test_overlapping_window_rejected_and_prior_ips_unaffected` — moved the `ERR_IPS_PERIOD_OVERLAP` assertion from create to activate; PRD §3.4 ties window hygiene to Activation ("Activation moves DRAFT → ACTIVE and enforces window hygiene"), while creation "starts in DRAFT".
- `test_08_investments_compliance.py::test_critical_reprice_auto_suspends_trust` — STEP 1c partial-coverage split: removed the `SUSPENDED` assertion (PRD §3.4 suspends on "the **creation** of a CRITICAL review"; this scenario reaches CRITICAL via the verbatim in-place update pathway, so suspension is not uniquely derivable); kept the covered assertions (single review, in-place severity flip to CRITICAL).
- `test_09_fees.py::test_different_operator_posts_successfully` — setup now funds income too; PRD §3.6's posting funds check requires `income_portion_cents ≤ available_income_cents`, so a principal-only trust must fail posting with `ERR_FEE_EXCEEDS_AVAILABLE_BALANCE`.
- Fee/DNI expected constants corrected in `test_09_fees.py` (`test_post_debits_both_buckets`, `test_reverse_restores_balances_exactly`) and `test_11_tax_filings.py` (5 assertions across 4 tests + `_dni_trust` docstring): the tests had computed the FINAL fee on a principal-only base, but PRD §3.6 states the base is "the sum of those as-of market values **plus the currently posted income and principal cash balances**". Recomputed per PRD (verified against Decimal ROUND_HALF_UP at the named steps): income portion 219,688 (base 201,000,000) / 220,157 (base 201,500,000); DNI 780,312 / 1,279,843 / 1,779,843; taxable 750,312 / 449,843. The implementation's actuals matched these recomputations exactly in every case.

**Fixes applied to `implementation/`:** none — every failure traced to the test artifact; no PRD-required check was removed or weakened, and no fields/endpoints were added.

## Step 8: Finalize PRD — 2026-08-14T01:25:00.000Z

Done. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1573_personal_trust_fiduciary_account/workspace/PRD_FINALIZED.md` with exactly one inline revision.

## Line counts
- PRD.md: 358 lines; PRD_FINALIZED.md: 358 lines; 0% line-count delta (single in-place sentence revision on line 172, +28 words).

## Changes
- **§3.4 (Investment Policy, Trading, and Drift Compliance) — revise** — appended "; an in-place update that raises an existing review's severity to CRITICAL is not a creation and does not suspend the trust" to the sentence "The creation of a CRITICAL review immediately suspends the trust, ACTIVE → SUSPENDED." — `implementation/services/calc.py:177-187` (in-place update branch has no suspension) vs `calc.py:188-206` (suspension only inside the new-review creation branch, guarded by `trust["status"] == "ACTIVE"`).

All other step_7_diff items were verified as already PRD-determined or pure test/fixture bugs, and required no edit:
- Deleted purpose-precedence test: impl checks the purpose standard only at open-voting (`implementation/routes/distributions.py:187-190`); create checks shape/ownership/existence/ACTIVE/OCC/cross-trust/beneficiary-active only (`distributions.py:44-77`) — exactly as PRD §3.3 pins.
- Fixture `with_document=True`: PRD §3.1 already requires an APPROVED document at acceptance.
- IPS overlap at activate: impl checks overlap only in `activate_policy` (`implementation/routes/investments.py:109-119`); create (`investments.py:53-70`) does not — matches PRD §3.4.
- Fee posting funds check and FINAL fee base including cash balances: impl matches PRD §3.6 verbatim (`implementation/services/calc.py:75` adds `income_balance + principal_balance` to the FINAL base).

## Per-edit pre-edit search log
- **Edit 1 (§3.4 in-place CRITICAL clause)**
  - (a) Subject: automatic trust suspension tied to CRITICAL compliance reviews (creation vs in-place severity flip).
  - (b) Enumerated impl paths: `implementation/services/calc.py:141-207` (`run_drift_check` — sole site of review creation at line 202 and in-place update at 182-187; suspension only at 204-206 inside the creation branch, ACTIVE-guarded); all three callers — `implementation/routes/investments.py:130` (IPS activation), `investments.py:258` (price update), `implementation/routes/trusts.py:215` (on-demand run-compliance-check) — all funnel through the same function; unrelated trust-status mutations checked for wording conflicts: manual suspend `trusts.py:148`, reinstate `trusts.py:167`, terminate `trusts.py:204`, termination-driven TERMINATED/CLOSED at `routes/termination.py:146,181`; confirmed via grep that `db.reviews[...] =` and `trust["status"] = "SUSPENDED"` have no other write sites; PRD §3.1's cross-reference ("imposed automatically the moment a CRITICAL compliance review is created") already uses "created", so it stays consistent verbatim.
  - (c) Wording adjustment: scoped the clause as a negation of "creation" for the in-place pathway only, preserving the existing "ACTIVE → SUSPENDED" guard (a new CRITICAL review created while already SUSPENDED — possible via price updates while suspended — does not re-suspend or double-bump, and the wording claims nothing there).

## Step 9: Complete PRD — 2026-08-14T01:43:00.000Z

All changes verified against the implementation. PRD_COMPLETED.md is written.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (358 lines, 66,216 chars) → `PRD_COMPLETED.md` (360 lines, 70,429 chars); char-delta **+4,213**, 32 diff hunks.

**Counts:** 23 ambiguity-pins, 9 mismatch-revisions (32 changes total).

### Changes

- §2.2 — insert — ambiguity — pins catch-all behaviors: undefined path → `ERR_RESOURCE_NOT_FOUND` (404), unsupported method on defined path → `ERR_VALIDATION` (405), unexpected failure → `ERR_INTERNAL` (500) — `implementation/app.py:25-35`
- §2.2 — revise — mismatch — error envelope no longer claimed to be 4xx-only (impl can emit 500) — `implementation/app.py:33-35`
- §2.3 — insert — ambiguity — negative/non-integer `offset` (and non-integer `limit`) → `ERR_VALIDATION` — `implementation/validation.py:84-106`
- §2.3 — insert — ambiguity — list sort ties on `created_at` break by creation order, earliest first — `implementation/services/workflow.py:101`
- §2.3 — insert — ambiguity — list endpoints accept optional exact-match filter query params (e.g. `trust_id`, `status`) — `implementation/routes/trusts.py:62-68` (and every other list route)
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — `implementation/services/workflow.py:18`
- §2.4 — revise — mismatch — entity timestamps are the exact logical-clock string at assignment, not normalized "three fractional digits" — `implementation/clock.py:39-43`, `implementation/services/workflow.py:10-18`
- §2.6 — insert — ambiguity — defines `pending_distribution_count` as counting requests in SUBMITTED/UNDER_REVIEW/INFORMATION_REQUESTED/VOTING/APPROVED — `implementation/serialize.py:17-18,41-43`
- §2.8 — insert — ambiguity — purchase costs added to the priority-11 funds-check enumeration — `implementation/routes/investments.py:178-183`
- §2.10 — insert — ambiguity — clock capability echoes the supplied `to_iso8601` string as `current_utc` and that exact string becomes subsequent stamps — `implementation/clock.py:39-43`, `implementation/routes/clock_routes.py:19-20`
- §3.1 — revise — mismatch — `governing_state` and `ein` are opaque strings with no format enforced (PRD claimed two-letter / XX-XXXXXXX formats) — `implementation/routes/trusts.py:33-34`
- §3.1 — insert — ambiguity — TrustDocument `version_number` must be a positive integer — `implementation/routes/documents.py:31-32`
- §3.1 — insert — ambiguity — supplied `prior_document_id` must name an existing TrustDocument, else `ERR_RESOURCE_NOT_FOUND` — `implementation/routes/documents.py:44-46`
- §3.1 — revise — mismatch — decline-acceptance `reason` is required but validated, not persisted (PRD claimed "recorded") — `implementation/routes/trusts.py:124-136`
- §3.2 — insert — ambiguity — mark-deceased bumps trust `version` only when ≥1 request was cancelled — `implementation/routes/beneficiaries.py:105-106`
- §3.2 — insert — ambiguity — no APPROVED instrument → shares left unchanged — `implementation/routes/beneficiaries.py:108-114`
- §3.2 — insert — ambiguity — no ACTIVE survivor in class → no reallocation, deceased's `share_bps` unchanged — `implementation/services/calc.py:248-254`
- §3.3 — revise — mismatch — open-voting precondition order pinned as request-state → trust ACTIVE → purpose → beneficiary ACTIVE → quorum → waterfall (PRD prose had beneficiary before purpose, contradicting §2.8 and impl) — `implementation/routes/distributions.py:182-209`
- §3.3 — insert — ambiguity — a non-deciding ballot updates tallies but does not advance trust `version` — `implementation/routes/distributions.py:258-266`
- §3.3 — revise — mismatch — disbursement gates evaluated trust-ACTIVE first, then request-APPROVED — `implementation/routes/distributions.py:276-282`
- §3.4 — insert — ambiguity — purchase/sale ledger rows carry `value_date` = current clock date and `source_entity_type` INVESTMENT_HOLDING — `implementation/routes/investments.py:209-212,287-290`
- §3.4 — revise — mismatch — `priced_at` refreshes to current clock time at any purchase (incl. merges), not only creation — `implementation/routes/investments.py:190,204`
- §3.4 — insert — ambiguity — concentration test: post-trade MV = total units × purchase price vs **pre-trade** `total_market_value_cents` — `implementation/routes/investments.py:171-177`
- §3.4 — insert — ambiguity — purchase cost must fit `available_principal_cents`, else `ERR_INSUFFICIENT_AVAILABLE_BALANCE` (funds-last) — `implementation/routes/investments.py:178-183`
- §3.4 — insert — ambiguity — overselling or selling a CLOSED holding → `ERR_VALIDATION` — `implementation/routes/investments.py:274-276`
- §3.4 — insert — ambiguity — resolve measures against the policy recorded on the review regardless of its status; TMV zero → `ERR_DRIFT_STILL_BREACHED` — `implementation/routes/compliance.py:82-92`
- §3.5 — insert — ambiguity — RECEIPT amount must be positive; ADJUSTMENT amount non-zero with explicit `bucket` — `implementation/routes/ledger.py:38-52`
- §3.5 — insert — ambiguity — posting responds 201 with `response_type` "array" of the created row(s) in append order — `implementation/routes/ledger.py:77-78`
- §3.6 — insert — ambiguity — `period_start` after `period_end` → `ERR_VALIDATION`; first FINAL assessment unconstrained — `implementation/routes/fees.py:53-55,72-77`
- §3.6 — insert — ambiguity — FINAL base uses each holding's current units × as-of price; holdings with no observation on/before cutoff contribute zero — `implementation/services/calc.py:62-76`
- §3.6 — revise — mismatch — `annual_fee_cents` is the tier sum rounded half up; quarterly derives from the **unrounded** tier sum ÷ 4 (PRD said "dividing the annual fee") — `implementation/services/calc.py:42-43`
- §3.6 — insert — ambiguity — FEE posting rows and reversal ADJUSTMENT rows carry `value_date` = current clock date — `implementation/routes/fees.py:157-163,220-226`
- §3.7 — revise — mismatch — statement window for non-calendar `fiscal_year_end_month` pinned (first of month after end-month in FY−1 through last of end-month in FY); PRD had claimed Jan 1–Dec 31 unconditionally — `implementation/services/workflow.py:36-48`
- §3.8 — revise — mismatch — tax-year window is always calendar Jan 1–Dec 31 of `tax_year` regardless of `fiscal_year_end_month` — `implementation/services/calc.py:275-276`
- §3.8 — revise — mismatch — require-amendment `reason` is required but validated, not persisted (PRD claimed "recorded") — `implementation/routes/filings.py:199-211`, `implementation/serialize.py:281-301`
- §3.9 — insert — ambiguity — each distribution line carries `beneficiary_id`, `beneficiary_class`, `amount_cents`; zero-amount lines append no ledger row; rows carry `value_date` = clock date and `source_entity_type` TERMINATION_CASE — `implementation/services/calc.py:318-347`, `implementation/routes/termination.py:131-140`
- §3.9 — revise — mismatch — close requires the filing whose `tax_year` equals the fiscal-year number containing `distributed_at` (not the calendar tax year containing it) — `implementation/routes/termination.py:161-176`
- §4 — revise — ambiguity — ledger modification guard covers PUT, PATCH, and DELETE (PRD named only PUT), in both the prose and the endpoint table — `implementation/routes/ledger.py:104-110`
