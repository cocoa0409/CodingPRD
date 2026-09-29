# Worklog — task_2201_programming_carriage_affiliate_agreement_administration

## Step 1: Create task directory — 2026-08-31T00:00:00.000Z

Created `tasks/task_2201_programming_carriage_affiliate_agreement_administration/` and `workspace/` subdirectory. Task directory name was pre-allocated by the caller (no index scan performed).

## Step 3: Copy shared files — 2026-08-31T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines, byte-identical to project-root source; verified on resume).

## Resume checkpoint — 2026-08-31T00:00:00.000Z

Resumed after a crash. Disk audit found only `worklog.md` and `workspace/INSTRUCTION.md` present. Missing/invalid: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, test_helpers/, test_suite/, workspace/implementation/, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md. Pipeline continues from Step 2.

## Step 2: Generate scaffold — 2026-08-31T21:49:55.000Z

Two prior subagent attempts were killed by the stream watchdog (600s of silence while reading the 73KB skill + reference/example corpus); a third was interrupted by a mid-response API server error. The run was recovered by resuming the same subagent with an incremental-write protocol (chunked Write/Edit calls, progress notes between calls) rather than restarting. Verbatim subagent summary:

All three scaffold artifacts are complete and lint-clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2201_programming_carriage_affiliate_agreement_administration/`
- `SCAFFOLD.yaml` (2584 lines, 166 KB) — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (4162 lines, 205 KB) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (6712 lines, 313 KB) — single key `scaffold_corner_design`

## SCAFFOLD.yaml counts
`domain_name: carriage-affiliate-admin`, `api_prefix: /carriage`

| | count |
|---|---|
| entities | 14 |
| state machines | 6 |
| concurrency rules (OCC) | 3 |
| calculations | 10 |
| validations (ordered ladder) | 49 |
| endpoints | 55 |
| errors | 62 |
| roles | 6 |

Plus a `domain_constants` block (39 constants) and a logical clock defaulting to `2026-08-01T00:00:00Z`.

## §1.8 difficulty design
All 9 §0.5 rules present, **27 instances**, every rule ≥ 2 differentiated instances: `dual_variant_calc` 3, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `boundary_precision_check` 4, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 3, `compensating_invariant` 2.

## §1.9 corner design
All 9 guide sections in canonical order, **88 instances = 76 full test recipes + 12 `excluded_because` stubs**:

| section | instances | stubs |
|---|---|---|
| entities | 10 | 0 |
| state_machines | 12 | 2 |
| calculations | 10 | 3 |
| validations | 13 | 2 |
| endpoints | 9 | 1 |
| errors | 16 | 0 |
| rbac | 8 | 0 |
| cross_cutting_complexity_layers | 8 | 4 |
| consistency_model | 2 | 0 |

## Verification
- All 62 error codes have at least one triggering test.
- Instance names unique across both design files; no cross-file collisions; every `excluded_because.difficulty_instance` resolves to a real §1.8 name; stubs carry no `test_recipe`; all 76 real recipes have `setup`/`setup_api_calls`/`trigger`/`assert` plus `distinguishing_aspect`.

Final linter verdict:

```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     14
  §1.8 instances scanned:     27
  §1.9 instances scanned:     76
  Calls scanned (§1.8+§1.9):  834

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two findings worth flagging for future runs: the linter role-checks `trigger` calls as well as `setup_api_calls`, so deliberate 403 tests must carry a negative-test instance name (`_cannot_`, `_rejects_`, `_forbidden`, …) — seven RBAC instances were renamed for this. Also, the claim-extraction guide has no claim-type table for Table 6, so all errors-section instances use `claim_type: error_triggerable`.

Orchestrator verification: all three files parse as valid YAML; corner design carries all 9 canonical sections in order; difficulty design carries 9 rules / 27 instances.

## Step 4: Generate PRD — 2026-08-31T22:18:00.000Z

PRD complete at `workspace/PRD.md`.

**Deliverable:** 519 lines, ends at §5 with no audit footer. Source of truth was `SCAFFOLD.yaml` only; neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim, byte-identical to the fixed source — verified) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 Logical Time · 2.6 Rates, Money and Rounding · 2.7 Optimistic Concurrency on Parent Revisions · 2.8 Path Resolution and the Order of Rejection · 2.9 Cascade Discipline and Compensation · 2.10 Two Different Interval Semantics
- §3 Business Logic: 3.1 Operator onboarding, rate card, credit posture · 3.2 Drafting/negotiating/executing an agreement · 3.3 Escalators, MFN caps and the billed rate · 3.4 Monthly reporting and the two fee variants · 3.5 Penetration compliance, breach escalation, cure · 3.6 Content rights, platform windows, territorial blackouts · 3.7 Audit rights, findings, underreporting recovery · 3.8 Marketing support, invoicing, cash application · 3.9 Renewal leverage and the second lifecycle dimension
- §4 Endpoint Definitions (4 columns: Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue (2 columns: Error ID, HTTP Status Code)

**Hard Contract 1 — Field-Name Coverage: PASS.** 161 required identifiers extracted mechanically from the scaffold (all entity `{ name: … }` fields across the 14 entities, every endpoint `input:` member including optional query params, all 13 `{pathParam}` names, and the settlement-summary inline `output:` object fields). All 161 appear verbatim in backticks. Two passes were run: the first surfaced exactly one gap, the `action` request field, which was fixed by adding an explicit paragraph in §2.8 naming `action` and its companion fields (`reason`, `suspension_reason`, `note`, `block_reason`, `amount_cents`); the second pass reported 0 missing. All 62 error IDs also appear in backticks in prose or the §5 table.

**Hard Contract 2 — Rule Coverage: PASS.** All 44 declared state-machine transitions across SM1–SM6 are present with preconditions and side effects; 31 are written as explicit `FROM → TO` arrows and the remaining 13 (both TERMINATE forms, `RENEWAL_ANALYSIS → LAPSED`, the CLEARED/ACTIVE→BLOCKED cascade forms, the four window-expiry forms, both WRITTEN_OFF forms, both VOID forms) are described in prose naming their from-states and conditions — each was individually re-read to confirm. All 49 validation rules are covered, and all 47 distinct validation `error_id`s appear; validation priorities are projected as the ordered 16-step gauntlet in §2.8 with "first failing rule decides, no side effect fires", plus local ordering restatements at each decision point (report acceptance, window clearance, blackout scheduling, invoice draft, invoice issue). All 10 calculations are given as step-by-step prose with pinned evaluation order and per-step rounding: C1 effective rate, C2 report license fee (PROVISIONAL/FINAL), C3 MFN benchmark, C4 audit recovery (PERIOD_RATE/CLOSING_RATE), C5 six-step invoice waterfall, C6 penetration compliance, C7 window occupancy, C8 blackout separation, C9 renewal leverage (BASE_CASE/DOWNSIDE), C10 marketing ledger. All 3 concurrency rules are in §2.7 with their exact field and 412 code; all cascade side effects are given with their pinned orderings; the three compensating operations (window UNBLOCK, invoice VOID, engagement return to FINDINGS_ISSUED) state their restore-to-pre-state invariants. No pseudocode, no symbolic operators, no fuzzy quantifiers.

**Hard Contract 3 — §3 Path Purity: PASS.** Every backtick token between the §3 heading and the §4 heading was extracted programmatically: 0 begin with `/`, 0 are a bare HTTP method, and 0 combine method with path. The OCC endpoint paths and the clock path live in §2, where paths are permitted.

**Coverage notes / judgement calls (2):** (1) RateCardEntry is documented as carrying `id` alone — no `created_at`, `updated_at` or `version` — following the scaffold's explicit field description over the skill's default for `common_fields: false`; AuditFinding and RenewalAnalysis were given `id` plus `created_at`, since C4 and C9 both order by `created_at`. (2) The scaffold's SM5 CLEARED→BLOCKED side-effect text implies a title with zero cleared windows can land in `EXCLUSIVE_UNCLEARED`, which contradicts the entity's PINNED four-arm coverage ladder (empty platform set → `UNDISTRIBUTED`); the PRD treats the entity's PINNED total ladder as authoritative and states it is re-evaluated in full after every event. Additionally, the SM4 START_FIELDWORK precondition "at least one reported period in the sample" carries no error ID in the scaffold; the PRD assigns it `ERR_AUDIT_PERIOD_NOT_REPORTED` (422), the existing code for that exact condition family, so the behaviour is determinate for the implementer.

Orchestrator verification: 518 lines, 5 top-level sections, ends mid-table at §5 error catalogue (complete — last row `ERR_PENETRATION_FLOOR_UNENFORCEABLE`). Mechanical cross-check against SCAFFOLD.yaml: all 62 declared error ids present in PRD; all 55 declared endpoint paths present in PRD.

## Step 5: Generate unit tests — 2026-08-31T23:35:00.000Z

Stage 1 and Stage 2 are both complete and verified.

## Files written

`test_helpers/` (9 files, Stage 1): `types.py` (roles, 27 enums, 14 entity TypedDicts with correct common-field branching), `api_client.py` (all 55 endpoint methods under `/carriage`), `api_errors.py` (all 62 error ids + PRD §5 status map registered), `assertions.py` (per-entity shape assertions plus ledger/settlement invariants), `constants.py`, `factories.py`, `test_users.py`, `fixtures.py` (~10 tiers of composite setup: lifecycle progression, reporting, audit chain, rights/blackouts, marketing, invoicing, renewal, MFN peers), `__init__.py`.

`test_suite/` (conftest + 16 test files): queue B in `test_01`–`test_09`, queue A in `test_20`–`test_26`. **171 test functions → 217 collected cases.**

## Coverage audit (machine-checked)

- **Queue A: 27/27 difficulty instances**, every one with ≥2 tests (2–4 each), 69 test functions.
- **Queue B: 76/76 non-stub corner instances**, every one with ≥1 test, 102 test functions.
- **12 `excluded_because` stubs: 0 tests**, and all 12 `difficulty_instance` cross-references verified to resolve to a real `name:` in the difficulty index.
- **0 instances skipped** — every instance cleared the PRD-first two-condition filter.
- 0 untagged tests, 0 dual-tagged tests, 0 orphan tags; every docstring's last line is exactly one `Design:` line.
- **527/527 substantive docstring quotes are verbatim in PRD.md** (whitespace-normalised literal match).
- 0 `skip`/`skipif`/`xfail` markers; the word "scaffold" appears nowhere; no `sys.path` hacks or direct framework imports in `test_suite`; `py_compile` and `pyflakes` clean.

## Design-index defects found during adjudication (PRD won every time)

Worth feeding back upstream — no instance was dropped, but individual recipe assertions were corrected:

1. Many recipes pin HTTP **422** for `ERR_INVALID_*_STATE`, duplicate-key and stale-version codes where PRD §5 pins **409/412**. Tests assert only `error_id` and let the PRD-derived status map adjudicate.
2. Recipes assert `license_fee_due_cents == null` on a `SUBMITTED` report; PRD §3.4 opens it at **0**.
3. Recipes assert a draft invoice stamps `invoice_id` on its source reports; PRD §3.8 says a draft **never** claims them.
4. The audit-adjustment round trip recipe expects fee 5,200,000 and `consecutive_compliant_periods` 1; PRD arithmetic yields **5,600,000** and **0**, and `ACCEPT_ADJUSTMENT` additionally requires the engagement to be `RECOVERY_INVOICED`/`COLLECTED` first.
5. One temporal-overlap recipe's final assertion is impossible under PRD §2.10's half-open rule (the "abutting" interval still overlaps); adjacency legality was proven a different way.
6. One recipe uses `distributor_type: SATELLITE`, not a declared enum member (substituted `DBS`).
7. Several recipes pin exact timestamp literals lacking the mandated three fractional digits — asserted non-null / second-prefix instead.
8. A corner recipe manufactures agreement staleness via a version bump PRD never states; rebuilt from a PRD-stated bump.

Two of my own Stage 1 helpers were also corrected after translator feedback: `reset_mfn` now sends the required `RESET`/`WAIVE` action (with a `waive_mfn` wrapper), and `setup_audit_recovery_invoice` now bills the findings-issuance month per PRD §3.8 rather than the reported month.

Orchestrator verification: `test_helpers/` holds all 9 expected files; `pytest --collect-only` reports 217 tests collected in 0.84s with no collection errors.

## Step 6: Generate implementation — 2026-08-31T23:35:00.000Z

The implementation is complete and verified.

## Modules

`workspace/implementation/` — 11 top-level modules + 13 route modules, all in-memory (Python dicts in `store.Store`), no file/SQLite/JSON persistence, no seeded data.

Foundation: `constants.py` (39 domain constants + enums), `errors.py` (all 62 error ids + `ApiError`), `store.py` (13 dict tables, logical clock, Decimal/ROUND_HALF_UP helpers, `touch`/`new_entity`/`serialize`), `envelope.py` (`meta`/`response_type`/`data` envelope, pagination limit 10/1/100), `validation.py` (typed field coercion, unknown-field rejection), `auth.py` (`X-User-ID`/`X-User-Role`, liaison scoping), `lookup.py` (13 kinds → per-entity 404 ids), `calc.py` (C1–C10: escalator/MFN rate, two fee variants, MFN benchmark, audit recovery, six-step invoice waterfall, occupancy, blackout hours, renewal leverage), `cascades.py` (coverage ladder, window blocking, commitment ledger, suspension/expiry/termination, pinned 6-step clock sweep), `common.py` (list/read helpers, OCC, both segregation-of-duties checks), `app.py` (`create_app`, error handlers, `PORT` env).

Routes: `clock`, `distributors`, `ratecards`, `titles`, `agreements`, `mfn`, `reports`, `audits`, `windows`, `blackouts`, `marketing`, `invoices`, `renewals`. Plus `requirements.txt` and `start.sh` (`exec python3 app.py`, chmod +x).

## Endpoint count

**55 of 55** registered, confirmed by enumerating `app.url_map` (53 business paths under `/carriage` + `GET /_clock` + `POST /_clock/set_current_utc`).

## Boot verification

`PORT=18325 bash start.sh` boots cleanly in ~1s; `GET /_clock` returns a well-formed envelope with `current_utc` exactly `2026-08-01T00:00:00.000Z`, `set_count` 0. All 13 collection endpoints report `total_count: 0` on a fresh boot, so per-test-server isolation is satisfied.

A 60-step end-to-end smoke run finished with **0 failures**, exercising: agreement execution (auto-opening LAUNCH_FEE and MARKETING_SUPPORT commitments), report submit/accept with both fee variants, the six-step waterfall (gross 96000000 → co-op band 0.12 → offset 1200000 → net 94800000), issuance/receivable/payment/write-off ageing (`ERR_WRITE_OFF_TOO_EARLY` before 120 days, success after), void compensation of an AUDIT_RECOVERY invoice returning the engagement to `FINDINGS_ISSUED` with `recovery_invoice_id` cleared and `findings_issued_at` retained, segregation of duties (403 when the findings issuer drafts the recovery invoice), blackout 24-hour separation (409), window clearance/coverage ladder, MFN reset with `NO_COMPARABLE`, audit findings and recovery, renewal leverage, and three clock advances driving the pinned sweep (window ACTIVE→EXPIRED, commitments FORFEITED). Both settlement invariants (`marketing_conserved_identity_holds`, `revenue_identity_holds`) held true throughout, and no `_`-prefixed internal fields leak into any serialized payload.

Four defects were found and fixed during verification: `routes/renewals.py` used lookup kind `"renewal"` instead of `"analysis"` (500 on create); the earlier-noted commitment FORFEITED ladder, title double version bump, and a bad `store` import in `blackouts.py`. The renewal-analysis lifecycle guard was also dropped, since the scaffold's validations table explicitly excludes that endpoint from `ERR_AGREEMENT_NOT_EXECUTED` and no alternative error id exists.

Orchestrator verification: `start.sh` present and correct (reads `$PORT`, `exec python3 app.py` in foreground); `prd-bench-local-run` available at `/home/ubuntu/.local/bin/prd-bench-local-run`.

## Step 7: Run tests and iterate — 2026-09-01T00:35:00.000Z

Debug plugin removed, no skip/xfail markers, results files retained as the passing evidence.

## Summary

**Iterations run:** 2. Iteration 1 surfaced 3 deterministic failures (identical in all 8 rounds — no flakiness anywhere in the suite). Iteration 2 was clean: **217/217 passed in all 8 parallel rounds**, union of failing tests = 0.

**Tests deleted:** none. All three failures were repairable — two via STEP 1c partial-coverage splits, one a pure Python bug.

**Fixes applied to `test_suite/`:**

- `test_01_resource_representation.py` — `test_rights_window_enum_and_range_constraints_enforced`: the test passed `window_start`/`window_end`/`exclusivity` as explicit kwargs *and* splatted `**overrides` containing the same keys, so 2 of 3 parametrisations died with `TypeError: got multiple values for keyword argument 'window_start'` before ever reaching the server. Merged into one dict that `overrides` updates. Pure test bug — the implementation's `window_end <= window_start` and `territory_code` checks were already correct.

- `test_21_agreement_lifecycle_depth.py` — `test_suspension_does_not_disturb_the_renewal_dimension`: removed `assert opened["negotiation_round"] == 0`.

- `test_06_error_conditions.py` — `test_analysis_cannot_open_before_the_renewal_window`: removed the same `negotiation_round == 0` assertion, and relaxed `renewal_analysis_started_at == "2028-06-01T00:00:00Z"` to a whole-second prefix match.

**Why the two `negotiation_round` assertions failed unique derivability (STEP 1b):** the cited sentence is PRD §3.9 *"The transition stamps `renewal_analysis_started_at` with the current logical instant and leaves `negotiation_round` at 0."* But START_ANALYSIS requires `lifecycle_status` `EXECUTED`/`SUSPENDED`, and the only route to `EXECUTED` runs through `SUBMIT_FOR_NEGOTIATION`, which §3.2 says *"increments `negotiation_round` by one"*. Every agreement eligible for START_ANALYSIS therefore necessarily has `negotiation_round >= 1`, making the literal reading unachievable. The two admissible readings — (A) START_ANALYSIS assigns 0, (B) START_ANALYSIS does not write the counter and "leaves it at 0" is descriptive prose — are both articulable, and (B) is the better-supported one: §3.2 says the counter *"records entries into negotiation, not exits from it"* and §3.9 says *"it never decreases"*, which forbids a 1→0 reset. The implementation follows (B) and is correct; only the non-derivable assertion was removed, while each test's PRD-verbatim assertions (`renewal_status == RENEWAL_ANALYSIS`, `lifecycle_status == EXECUTED`, `ERR_RENEWAL_WINDOW_NOT_OPEN`, `renewal_analysis_started_at` stamped, `suspension_reason == MANUAL_SUSPENSION`) were all kept.

The relaxed timestamp assertion is the same class of over-pinning the worklog records the generator having already corrected elsewhere: PRD §2.4 mandates three fractional digits for `created_at`/`updated_at` but never pins the serialisation of `renewal_analysis_started_at`, so `"...T00:00:00Z"` vs `"...T00:00:00.000Z"` is not derivable. §2.6 (*"Instants are compared at whole-second resolution"*) supplies the faithful comparison, which still verifies the transition stamps the correct logical instant.

**Fixes applied to `test_helpers/`:** none required — no fixture, factory, or role-header helper constructed a PRD-inconsistent precondition.

**Fixes applied to `implementation/`:** none. No implementation defect was found; every failure traced to the test layer. Notably I did not weaken the `negotiation_round` behaviour to satisfy the assertion, since PRD's "never decreases" rule requires it.

**Stability note:** the suite has no threading, no wall-clock reads, and no randomness — all time flows through the server's logical clock, and `app.py` runs `threaded=False` with an env-driven `PORT`. Storage is verified pure in-memory (no `open`/sqlite/pickle/json-dump/`/tmp` anywhere in the implementation) with no startup seeding, so `per-test-server` isolation wipes state completely. That is consistent with the observed result: identical failures in all 8 rounds of iteration 1 and zero variance in iteration 2.

Orchestrator verification: all 8 `results.{1..8}.json` report `passed == total == 217`. No `skip`/`xfail` markers anywhere in `test_suite/` or `test_helpers/` (sole grep hit is docstring prose). 217 tests still collect, confirming zero deletions. No persistence primitives in `implementation/` (sole `open(` hits are the `renewal_window_open` helper name).

## Step 8: Finalize PRD — 2026-09-01T00:50:00.000Z

PRD_FINALIZED.md is written. Summary:

## Line counts
- `PRD.md`: 518 lines; `PRD_FINALIZED.md`: 518 lines (0% line delta — both edits are in-line within existing paragraphs; +2 sentences, ~1 sentence revised).

## Changes

- **§2.4 Resource Identity, Timestamps and Revision Counters** — *insert* — PRD pinned "three fractional digits" only for `created_at`/`updated_at`; added that **every** instant-valued property is serialised identically (ISO 8601 UTC, trailing `Z`, exactly three fractional digits, fractional part truncated to milliseconds), and that unset instants come back as `null`. Traces to the Step 7 relaxation of `renewal_analysis_started_at == "2028-06-01T00:00:00Z"` → whole-second prefix. Impl: `implementation/store.py:38-43` (`iso()`), applied universally at `store.py:220-221` (`_to_json`), plus `routes/clock.py:17`.

- **§3.9 Renewal Leverage and the Second Lifecycle Dimension** — *revise* — replaced "leaves `negotiation_round` at 0" (unachievable: every START_ANALYSIS-eligible agreement has passed through `SUBMIT_FOR_NEGOTIATION`, so the counter is ≥ 1) with "does not write `negotiation_round` at all, leaving whatever value the lifecycle dimension of §3.2 has already driven that counter to." Impl: `implementation/routes/agreements.py:364-381` (START_ANALYSIS branch writes only `renewal_status` and `renewal_analysis_started_at`).

- Step 7's third item (`test_01` `test_rights_window_enum_and_range_constraints_enforced`) was a pure Python kwargs-collision bug in the test; PRD §3.6 (line 268) and §2.8 item 5 already determine `window_end > window_start` and the two-uppercase-letter `territory_code`. **No PRD edit.**

## Per-edit pre-edit search log

**Edit A — §2.4 instant serialisation**
- (a) Subject: rendering of every instant-valued field in API responses, not just `renewal_analysis_started_at`.
- (b) Paths enumerated/read: `store.py:38-43` `iso()`; `store.py:209-232` `serialize()`/`_to_json()` (the single funnel — every `datetime` in every record passes through it); `envelope.py:22-24` `_request_timestamp()` (same format for `api_request_timestamp`); `routes/clock.py:17` explicit `iso(current_utc)`; `store.py:20-35` `parse_iso()` (accepts arbitrary input precision, keeps microseconds internally → `iso()` truncates via `microsecond // 1000`). Grepped the full field inventory of `_at`/`_date`/`_start`/`_end`/`_deadline`/`_utc` names across `routes/*.py` + `*.py` and checked each origin: `field("datetime", …)` for `term_start_date`/`term_end_date` (`routes/agreements.py:66-67,154`), `window_start`/`window_end` (`routes/windows.py:37`), `blackout_start`/`blackout_end` (`routes/blackouts.py:37`), `linear_premiere_at` (`routes/titles.py:23`), `performance_deadline` (`routes/marketing.py:33`), `to_iso8601` (`routes/clock.py`); server-stamped `now()`/`current` for `executed_at` (`routes/agreements.py:119,281`), `accepted_at`, `enforced_at`, `issued_at` (`routes/invoices.py:267`), `findings_issued_at` (`routes/audits.py:172`), `renewal_offer_sent_at` (`routes/agreements.py:395`), `last_reset_at` (`routes/mfn.py:101` init `None` → `calc.py:201,213` datetime).
- (c) Adjustments made: (1) used "among them" instead of an exhaustive list, so no field is implicitly excluded; (2) explicitly excluded `sample_period_start`/`sample_period_end` from the claim by not listing them — verified they are `field("period")` strings (`routes/audits.py:43-44`), i.e. `YYYY-MM`, never instants, so a universal "all date-ish fields" phrasing would have been a new mismatch; (3) said "truncated to milliseconds" rather than "rounded", matching `microsecond // 1000`; (4) added the null clause because `iso(None)` returns `None` and several of these fields (`executed_at`, `last_reset_at`, `enforced_at`, `issued_at`, `findings_issued_at`, `renewal_*_at`) initialise to `None`.

**Edit B — §3.9 `negotiation_round` on START_ANALYSIS**
- (a) Subject: every write to `negotiation_round`.
- (b) Paths enumerated/read (grep `negotiation_round` across all impl `.py`, 4 sites, all read in context): `routes/agreements.py:110` draft init `0`; `:246` `SUBMIT_FOR_NEGOTIATION` `+= 1`; `:254` `RETURN_TO_DRAFT` explicitly leaves it (comment "records entries into negotiation, not exits"); `:402` `REOPEN_ANALYSIS` `+= 1`. START_ANALYSIS (`:364-381`) contains no write. Cross-checked the surviving PRD prose for each: §3.2 line 185 (init 0), line 191 (increment on submit, untouched on return-to-draft), §3.9 line 383 (increment on reopen, "never decreases") — all four remain accurate and were left verbatim.
- (c) Adjustments made: chose "does not write `negotiation_round` at all" over "resets/leaves at 0", and pointed at §3.2 as the source of the current value, so the sentence stays true for the `negotiation_round >= 1` agreements that are the only ones reachable by START_ANALYSIS while not contradicting §3.9's "it never decreases".

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` yields 8 lines — exactly two in-paragraph revisions (line 91 §2.4, line 365 §3.9), no new sections, no line-count change.

## Step 9: Complete PRD — 2026-09-01T01:35:00.000Z

Done. `PRD_COMPLETED.md` is complete.

## Source vs completed

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` | 518 | 108,794 |
| `workspace/PRD_COMPLETED.md` | 518 | 125,427 |

Char delta **+16,633**. Line count identical (518 → 518): 51 existing lines revised in place, **zero** new lines, paragraphs or sections added.

## Counts
- **47 ambiguity-pins** (PRD was silent; inline prose added to state what impl does)
- **9 mismatch-revisions** (PRD asserted something impl does not do)

## Every change

- §2.1 — insert — ambiguity — a `DistributorLiaison` gets 403 on single reads of titles/rate-card rows and a silently empty page on those collections, since neither kind resolves to an operator — `auth.py:80-97`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 20 uppercase-alphanumerics; `api_request_timestamp` reads real wall-clock, not the logical clock — `envelope.py:18-24`
- §2.3 — insert — ambiguity — pagination breaches → `ERR_INVALID_REQUEST` 400, empty string = absent; `created_at` ties break by insertion sequence, `id` never a sort key; rate-card rows list in publication order — `envelope.py:58-74`, `store.py:205`
- §2.3 — insert — ambiguity — exhaustive per-collection filter names, exact-string comparison, empty filter ignored, any other query param → `ERR_INVALID_REQUEST` — `common.py:36-46`, `envelope.py:93`
- §2.4 — insert — ambiguity — rates/ratios render as JSON numbers with trailing zeros dropped (`1.0400` → `1.04`) — `store.py:219-232`
- §2.5 — revise — ambiguity — forward comparison truncates both sides to whole seconds; response is the singleton `{current_utc, set_count}` at 200 — `clock.py:22-37`
- §2.5 step 1 — insert — ambiguity — an `EXECUTED` agreement already `RENEWED` is skipped by the expiry sweep — `cascades.py:283-289`
- §2.5 step 6 — **revise — mismatch** — titles are re-derived from steps 1, **2** and 3, not only 2 and 3 — `cascades.py:291-292, 345`
- §2.6 — insert — ambiguity — client-supplied rates are stored verbatim and never re-rounded on write — `ratecards.py:22-39`, `agreements.py:68`
- §2.8 rule 5 — insert — ambiguity — further malformed-interval shape cases, plus two shape rules evaluated late (after band 7, before band 8) — `invoices.py:78-87, 244-245`
- §2.8 rule 5 — **revise — mismatch** — `amount_cents` is exempt from the negative-money shape rule — `invoices.py:237`
- §3.1 — insert — ambiguity — `legal_name` collision is `ERR_INVALID_REQUEST` 400, after field checks and the role test — `distributors.py:31-33`
- §3.1 — insert — ambiguity — both PATCH fields optional; a call supplying neither is accepted and still bumps `version` — `distributors.py:66-82`
- §3.1 — revise — ambiguity — `reason` ≤500 chars accepted but never persisted; credit-review has no state machine, every action legal from every status — `distributors.py:96-108`
- §3.1 — insert — ambiguity — `RELEASE_HOLD` refusals are `ERR_INVALID_REQUEST`, receivable test first — `distributors.py:110-114`
- §3.1 — insert — ambiguity — `SUSPEND`/`TERMINATE` leave `credit_hold_reason` intact, `REACTIVATE` resets it to `NONE`, none of the three cascades — `distributors.py:121-140`
- §3.2 — insert — ambiguity — `contract_code` 1–100 chars, uniqueness spans the operator's agreements in **every** lifecycle status — `agreements.py:65, 85-93`
- §3.2 — insert — ambiguity — every amendable field optional, an empty amendment re-stamps rates and bumps `version`; `term_start_date` not amendable; incoherent `term_end_date` → 400 — `agreements.py:148-169`
- §3.2 — **revise — mismatch** — the pre-execution state test precedes the term-coherence test (409 beats 400) — `agreements.py:160-169`
- §3.2 — insert — ambiguity — run-out term on `SUBMIT_FOR_NEGOTIATION` → `ERR_INVALID_AGREEMENT_STATE`, checked before the operator test — `agreements.py:236-244`
- §3.2 — insert — ambiguity — out-of-term `EXECUTE` → `ERR_INVALID_AGREEMENT_STATE`, checked after the operator test — `agreements.py:267-271`
- §3.2 — **revise — mismatch** — `REINSTATE` order is operator posture → breach counter → term liveness; dead term → `ERR_INVALID_AGREEMENT_STATE` — `agreements.py:311-327`
- §3.2 — insert — ambiguity — expiry resets `suspension_reason` to `NONE`; `executed_agreement_count` never goes below 0 — `cascades.py:204-216`
- §3.2 — insert — ambiguity — any window expired by a sweep has `block_reason` reset to `NONE` — `cascades.py:69-77`
- §3.2 — insert — ambiguity — termination resets `suspension_reason`, floors the counter at 0; the `NEGOTIATING` form runs no cascade — `cascades.py:226-244`, `agreements.py:334-340`
- §3.3 — insert — ambiguity — agreement-level stamping also writes `applied_escalator_years`; report-level pricing does not — `calc.py:68-77`
- §3.3 — insert — ambiguity — reset re-prices reports in `created_at` order and re-adds `audit_adjustment_cents` to an `AUDIT_ADJUSTED` report — `mfn.py:45-53`
- §3.3 — insert — ambiguity — `WAIVE` also requires `expected_agreement_version` (OCC before the clause-status check), re-stamps only the agreement, and both actions return the clause — `mfn.py:124-155`
- §3.4 — insert — ambiguity — `billable_subscribers` is null until acceptance, never 0 — `calc.py:128`
- §3.4 — insert — ambiguity — `note` ≤2000 chars never persisted; only `ACCEPT`/`DISPUTE` test agreement lifecycle — `reports.py:157-243`
- §3.4 — insert — ambiguity — the agreement's `version` rises exactly once whether or not acceptance auto-suspends it — `reports.py:200-219`
- §3.4 — insert — ambiguity — `ACCEPT_ADJUSTMENT` resolves the engagement via a citing finding; missing finding and wrong status share `ERR_INVALID_ENGAGEMENT_STATE` — `reports.py:145-256`
- §3.5 — insert — ambiguity — after an audit flip, `penetration_compliance_status` is left untouched when `penetration_breach_count` is 0 — `audits.py:195-198`
- §3.6 — insert — ambiguity — `rights_status` has no state machine (any target from any source, re-assertion legal); exactly one `version` bump including the destructive case — `titles.py:55-76`
- §3.6 — **revise — mismatch** — containment is inclusive at both bounds (`window_end <= term_end_date`), not term-end-exclusive — `windows.py:156-159`
- §3.6 — **revise — mismatch** — the clock never expires a `PLANNED` window; only agreement expiry/termination does — `cascades.py:311-321, 69-77`
- §3.6 — insert — ambiguity — `UNBLOCK` check order (state → agreement → title → blackout → occupancy) and re-stamping of `concurrent_licensee_count` — `windows.py:182-205`
- §3.6 — insert — ambiguity — `monthly_blackout_hours` is a scheduling-time snapshot, never revised on peers — `blackouts.py:65-96`
- §3.7 — insert — ambiguity — the 24-month survival test applies only when `lifecycle_status` is `EXPIRED`; clamped calendar-month arithmetic; equality passes on both halves — `cascades.py:353-363`
- §3.7 — insert — ambiguity — `START_FIELDWORK` check order (status → lifecycle → rights survival → sample content) — `audits.py:109-134`
- §3.7 — insert — ambiguity — several findings may cite the same report; nothing dedupes them — `audits.py:225-272`
- §3.7 — insert — ambiguity — `CLOSE_NO_FINDING` also zeroes `total_reported_subscribers` — `audits.py:212-213`
- §3.7 — insert — ambiguity — interest months are counted from midnight UTC **opening** the last calendar day of `period_month` — `calc.py:250`, `store.py:55-62`
- §3.7 — **revise — mismatch** — `audit_adjustment_cents` and `license_fee_due_cents` **accumulate** (`+=`); an already-`AUDIT_ADJUSTED` report keeps that status — `audits.py:186-189`
- §3.8 — insert — ambiguity — opening a commitment is ungated on lifecycle and accepts a past `performance_deadline` — `marketing.py:24-54`
- §3.8 — insert — ambiguity — `earned_cents` of 0 accepted, deadline test strict, no status gate; full status ladder pinned (`FORFEITED` first, `SETTLED` needs `billed_cents > 0`) — `marketing.py:74-107`, `cascades.py:140-164`
- §3.8 — insert — ambiguity — an `AUDIT_RECOVERY` invoice's `period_month` is stored verbatim, never validated against `findings_issued_at` — `invoices.py:125`
- §3.8 — insert — ambiguity — a zero `recovery_amount_cents` engagement → `ERR_NO_BILLABLE_REPORTS` at draft — `invoices.py:104-112`
- §3.8 — insert — ambiguity — step 2 still runs on an `AUDIT_RECOVERY` invoice, so `coop_cap_pct` is selected from the recovery gross and stamped — `calc.py:365-374`
- §3.8 — insert — ambiguity — issuance never re-runs the waterfall; it consumes the drafting-time plan, capped per line by current `earned_unbilled_cents` — `invoices.py:183-198`
- §3.8 — **revise — mismatch** — a non-positive `amount_cents` is `ERR_PAYMENT_EXCEEDS_BALANCE`, not a shape error — `invoices.py:296`
- §3.8 — insert — ambiguity — a write-off never releases a credit hold and never unclaims its source reports — `invoices.py:321-343`
- §3.9 — insert — ambiguity — the renewal window is measured in whole days (fraction discarded); lifecycle test precedes the window test — `cascades.py:351-352`, `agreements.py:363-377`
- §3.9 — **revise — mismatch** — running a leverage model has **no** lifecycle, renewal-status or window gate — `renewals.py:32-34`
- §3.9 — insert — ambiguity — `RENEW` extends `term_end_date` by 36 **calendar** months with the day clamped down — `agreements.py:417-419`, `store.py:69-82`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405 and `ERR_INTERNAL` 500 exist outside the catalogue, in the same envelope — `app.py:30-47`

Cross-checks run beyond the pins: the §4 endpoint table matches impl exactly (55/55, no extras or omissions on either side), the §5 code table matches `errors.py`'s `ERROR_HTTP` map, and §2.7, §2.9, §2.10, §3.5's counter rules and §3.8's settlement roll-up (11 fields) all already agreed with impl.

## Pipeline complete — 2026-09-01T01:35:00.000Z

All nine steps have valid artifacts on disk. Step 9 edited only `PRD_COMPLETED.md`, so the Step 7 evidence (`results.{1..8}.json`, 217/217 in every round) remains current for the unchanged `implementation/` and `test_suite/`.
