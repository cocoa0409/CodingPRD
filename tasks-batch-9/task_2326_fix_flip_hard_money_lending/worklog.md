# Worklog — task_2326_fix_flip_hard_money_lending

## Step 1: Create task directory — 2026-09-01T17:02:51.777Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2326_fix_flip_hard_money_lending/` and its `workspace/` subdirectory. Task directory name was pre-allocated by the caller (no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T19:17:13.621Z

Done. All three scaffold artifacts for task 2326 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2326_fix_flip_hard_money_lending/`)
- `SCAFFOLD.yaml` (2,386 lines) — §1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (3,307 lines) — single top-level key.
- `SCAFFOLD_CORNER_DESIGN.yaml` (6,259 lines) — single top-level key.

**SCAFFOLD.yaml counts**
- 14 entities, 11 state machines / 77 transitions, 2 concurrency (OCC) rules, 12 calculations, 29 strictly-ordered validation rows (priorities 1–28, 30), 53 endpoints, 64 error codes, 7 RBAC roles.
- Profile: primary archetype `ledger_reconciliation`, secondary `compliance_audit`; layers `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`, `optimistic_concurrency`; topology `graph`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`.
- Hard mechanics: three-cap nested-min loan sizing with a single-pass (non-fixed-point) interest reserve, dual draw-release variants (inspection 10% retainage vs photo 20% + 0.50 cap, per-line round-then-sum), mid-period note/default rate splitting, waiver-headroom and FINAL_UNCONDITIONAL gates, three parallel loan axes, and a full default → foreclosure → REO completion → disposition settlement with a commitment-conservation identity (`commitment_balance_check_cents == 0`).

**Difficulty design**: 9 rule_ids × 26 instances (3 each except `resource_temporal_overlap` at 2).

**Corner design**: 9 sections (exactly the guide's snake_cased section names), 82 entries = 57 full `test_recipe` instances + 25 `excluded_because` stubs. Per-section: entities 12, state_machines 15, calculations 17, validations 17, endpoints 6, errors 4, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1.

**Coverage notes**
- All 64 declared error codes are triggered or stub-attributed across the two design files.
- Every claim_type row of the guide's tables that applies is covered (entities 11 rows + `graph` topology; state machines 7 rows + `parallel` + `guarded_transitions` + all 6 side-effect patterns; validations 3 rows + all 6 patterns; endpoints all 6 patterns; RBAC exclusive/shared/denial + `peer_roles` + segregation of duties; both declared OCC rules get their own stale-version instance; consistency `immediate`).
- All 25 stub citations resolve to real difficulty-instance names; names are unique across both design files; no stub carries a `test_recipe`.
- Generated purely from the scenario text plus the skill spec — no sibling task directory was listed, read, or grepped at any point.

**Linter verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     26
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1854

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-09-01T19:17:13.621Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_2326_fix_flip_hard_money_lending/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T19:45:32.143Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2326_fix_flip_hard_money_lending/workspace/PRD.md` — 487 lines. Neither withheld design file was opened, and no sibling task directory was read.

## Structure

- **§1 Introduction** — 3 paragraphs (domain framing, actor cast, the two cross-cutting constraints: integer-cent ledger discipline and the logical clock).
- **§2 Global Specifications** — 12 subsections: 2.1 RBAC (all 7 roles, both `entity_backed` identities translated into ownership-comparison prose, `inspector_id` explicitly flagged as *not* a foreign key, `PlatformAdmin` bypass scoped to ownership only); **2.2 pasted byte-verbatim** (mechanically verified); 2.3 Pagination + the full filter inventory; then 9 domain-derived subsections — Logical Clock, Commitment Conservation and the Loan Money Buckets, Money/Precision/Rounding, Common Resource Properties, Resolving Identifiers in Paths and Bodies, OCC on Supersede Writes, Cascades and Compensating Reversals, Segregation of Duties, Rejection Precedence (a 29-step ladder mirroring the scaffold's priority order exactly).
- **§3 Business Logic & Workflows** — 9 subsections (sponsor scoring/recertification/suspension; property revaluation + trades + scope validation; sizing; credit decision and closing; draw intake and the two verification legs; draw underwriting, waivers, contractor controls, disbursement; accrual/sweep/payments/payoff; extensions and exit monitoring; default/foreclosure/completion/REO).
- **§4 Endpoint Definitions** — 4-column table, 53 rows.
- **§5 Error Code Catalogue** — 2-column table, 64 rows. Document ends here.

Every §2 and §3 heading is domain-named; none reuse the example PRD's subsection names or grouping.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 176 required, 176 present, 0 missing
- endpoints[].request_body: 85 required, 85 present, 0 missing
- endpoints[].query_params: 0 separate required (this scaffold carries query
  filters inside endpoints[].input with a trailing `?`, so all filter names are
  inside the 85 above), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint +
  expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 77 checked, 77 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 side-effect lines + 29 applies_to
  scopes checked, 83 expressed, 0 missing
- entities[].fields[] structured content: 176 checked, 176 reconstructible from
  prose, 0 missing
- sibling-branch symmetry: 13 groups checked, 13 with equal prose density,
  0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1025
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Coverage notes

- **§4 verified against the scaffold programmatically**: all 53 (method, path) pairs and their authorized-role *sets* match exactly — no missing, extra, or role-drifted rows.
- **§5 verified programmatically**: all 64 error IDs present with identical HTTP statuses and in the scaffold's own order.
- **All 77 transitions** are covered; 50 appear in explicit `FROM → TO` arrow form and the remaining 27 (the fan-in cascades — five `→ SUPERSEDED`, four `→ SUSPENDED`, three `→ VOID`, four `→ EXITED`, three `→ FORECLOSED`, three `→ LENDER_COMPLETING`, three `→ PAID_OFF`, two `→ RESOLVED`, two `→ WITHDRAWN`) are expressed as enumerated source-status sets in the cascade prose, which is more faithful to how they actually fire.
- **All constants translated to prose values**, not symbol names: the tier percentage matrices, the 0.10/0.20 retainage split, the 0.50 photo ceiling, 3,000,000 cents, 3 photos per line, the 360-day basis, the 600 bp default spread, 100/50 bp extension fee and step, 90-day exit watch / redemption windows, the 90-minute travel buffer, the 0.50 single-line cap, 3 revision rounds, 2 extensions, 10-day delinquency aging, 0.06 selling cost and 0.20 completion cap.
- **Zero pseudocode**: scanned clean for `>=`, `<=`, `!=`, `==`, `->`, `IN {`, `min(`, `max(`, `floor(`, `round_half_up(` and bare `/10000`. All rounding/flooring order is pinned in prose, including the three explicitly divergence-producing spots (per-line-then-sum on draw release, floor-each-cap-before-min on sizing, two-independent-roundings on split-rate accrual) and the snapshot-before-capitalisation ordering on the reserve sweep.
- **Deliberate divergences preserved as intended, not smoothed over**: sizing-pass vs decision-pass allocation producing different `sized_initial_funding_cents` and `alloc_initial_funding_cents`; the reserve priced on `quoted_rate_bps` in both passes; the single-correction-round rule with unreallocated residual slack; `pricing_tier` snapshotting so recertification cannot reprice in-flight applications; `open_waiver_headroom_cents` permitted to go negative.
- No fuzzy quantifiers ("approximately", "roughly", "conservatively", etc.) anywhere in the document.

## Step 6: Generate implementation — 2026-09-01T20:26:17.000Z

(Steps 5 and 6 were launched concurrently in a single message; Step 6 returned first.)

Implementation complete and verified end-to-end.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2326_fix_flip_hard_money_lending/workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 17 | Foreground launcher: `cd $(dirname $0)`, `PORT=${PORT:-8080}`, installs flask only if missing, `exec python3 app.py` |
| `app.py` | 74 | App factory, blueprint registration (`/lending` prefix + un-prefixed clock), `ApiError`/404/405/400/500 handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `core.py` | 474 | In-memory `Store` (14 dicts, empty at boot), logical clock, response envelope, `ApiError`, auth/RBAC/ownership, field validators, pagination, money/decimal helpers |
| `calc.py` | 408 | All pure formulas + constants: experience scoring/tiers, sizing caps & the two allocation passes, draw release, accrual rate split, payoff quote, extension repricing, DOM/exit watch, waiver coverage/headroom, REO selling costs, completion cap, conservation check |
| `serialize.py` | 429 | Per-entity lookups (one 404 code each), collection helpers, 14 serializers |
| `services.py` | 205 | Ledger writes, cascades (sponsor suspension → applications WITHDRAWN → lines VOID), compensating reversals (supersede/suspend), exit-axis freeze, property cascade, settlement, loan-writable/serviceable guards |
| `routes/origination.py` | 722 | Borrowers, properties, contractors, applications, scope lines, sizing, decision, close |
| `routes/draws.py` | 629 | Draw requests, inspection visits, reports, photo verification, review, fund, draw line items, lien waivers |
| `routes/servicing.py` | 555 | Loan reads, accruals, ledger, payments, extensions, exit milestones, default declaration, foreclosure (case/takeover/completion-budget/disposition) + `POST /_clock/set_current_utc` |
| `routes/__init__.py`, `requirements.txt` | — | package marker; `flask>=3.0` |

## Endpoint count
53 Flask rules registered. A programmatic diff against the SCAFFOLD endpoint table shows **0 missing, 0 extra** (52 `/lending` endpoints + `POST /_clock/set_current_utc`; `GET` and `PATCH /lending/rehab-line-items/{id}` share a path).

## Verification
Server booted from `start.sh` (with `PORT` set and with `PORT` unset → 8080) and answered 200. Two scripted end-to-end scenarios ran green (0 unexpected statuses across ~90 calls): full origination → draw (inspection) → accrual → payment → 2 extensions → default → foreclosure → takeover → completion budget → disposition; and a second run covering RECERTIFY, valuation-driven `ERR_SIZING_STALE`, `ERR_LOAN_AMOUNT_EXCEEDS_LIMIT`, `ERR_STALE_LOAN_VERSION` (412), PHOTO verification with the 50% cap, `ERR_VERIFICATION_METHOD_MISMATCH`, `ERR_INSUFFICIENT_PHOTO_EVIDENCE`, `ERR_CONTRACTOR_NOT_PAYABLE`, `ERR_WAIVER_HEADROOM_EXCEEDED`, `ERR_SEGREGATION_OF_DUTIES` (403), `ERR_JOINT_CHECK_ACK_REQUIRED`, `ERR_PAYOFF_SHORT`, exact payoff → PAID_OFF/EXITED/property SOLD, plus 401/403/404/400 guards. `commitment_balance_check_cents` read exactly 0 after every money-moving write in both runs.

## Notable design decisions
- **One bug found and fixed by the smoke run**: REO disposition originally added the completion advance to `funded_principal_cents` without draining it out of `undisbursed_holdback_cents`, leaving `commitment_balance_check_cents = -budget`. Now the advance moves *out of* the holdback and the residual holdback is decommitted, so the identity stays 0.
- **Reserve at disposition**: PRD §3.9 enumerates only the holdback buckets, so `interest_reserve_balance_cents` is left untouched at disposition (the PRD's closing claim `repaid + decommitted == committed` therefore holds exactly whenever the reserve has been exhausted, which the paragraph presumes). `check == 0` — the invariant stated twice — holds unconditionally.
- **Accrual ordering** = overlap (19) → gap (20) → beyond-clock (21); fixed 360-day accrual basis (`day_count_convention` only affects the payoff quote); the sweep capitalises after `principal_snapshot_cents` is taken; CURRENT→DELINQUENT stamps `delinquent_since = period_end`.
- **`ERR_LOAN_NOT_SERVICEABLE`** is applied only where SCAFFOLD lists it: draw create/review/fund, extensions, exit milestones (payments and inspections are not gated); a DEFAULT reinstatement payoff is blocked only once a foreclosure case reaches RESOLVED.
- **Reachability tuning** so every code is hittable: `ERR_SIZING_REQUIRED` (DRAFT passes the decision state check), `ERR_VISIT_ALREADY_SCHEDULED`, `ERR_EXTENSION_LIMIT_REACHED` before `ERR_EXTENSION_BLOCKED_BY_EXIT_WATCH`, milestone field-shape (`ERR_INVALID_REQUEST`) before `ERR_MILESTONE_BACKDATED`, OCC (412) before case-state (409) on completion-budget.
- Auth reads `X-User-Role` with an `X-Role` fallback; the clock endpoint is exempt from `ERR_UNAUTHENTICATED` but still 403s a non-PlatformAdmin role. `decimal.Decimal` throughout with the pinned per-line-then-sum and floor-each-cap-before-min orders; `months` on extensions has no upper bound (none is specified).

## Step 5: Generate unit tests — 2026-09-01T21:36:40.000Z

Stage 2 is complete. Full generation report:

## Files written

**`test_helpers/`** (Stage 1, 9 modules, 2,483 lines) — `__init__.py` (181 re-exports), `types.py`, `api_client.py`, `api_errors.py` (64 error IDs + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

One Stage-1 correction made this session: `assertions.assert_error_envelope` asserted `response_type == "ERROR"` and `"data" not in body`, which contradicts PRD §2.2 (`"error"` lowercase, with `error_id`/`message` **inside** `data`). Rewritten to the PRD envelope.

**`test_suite/`** — 13 modules, 110 tests:

| file | tests |
|---|---|
| `test_01_sponsor_scoring_and_lifecycle.py` | 10 |
| `test_02_scope_validation_and_revision.py` | 8 |
| `test_03_sizing_and_credit_decision.py` | 11 |
| `test_04_closing_and_money_buckets.py` | 7 |
| `test_05_draw_intake_and_supersede.py` | 7 |
| `test_06_draw_verification_legs.py` | 10 |
| `test_07_draw_release_and_disbursement.py` | 11 |
| `test_08_lien_waivers_and_contractor_controls.py` | 10 |
| `test_09_accrual_payments_and_payoff.py` | 13 |
| `test_10_extensions_and_exit_monitoring.py` | 5 |
| `test_11_default_foreclosure_and_reo.py` | 6 |
| `test_12_authorisation_and_priority_order.py` | 6 |
| `test_13_envelopes_identifiers_and_schema.py` | 6 |

## Queue counts and coverage

- **Queue A (Difficulty)**: 52 tests. All 26 instances (9 rule_ids) at exactly 2 tests each — target met, none under.
- **Queue B (Corner)**: 58 tests. All **57 non-stub** instances covered at ≥1 test.
- Zero orphan tags, zero dual tags, zero stub-tagged tests, zero untagged tests.
- `pytest --collect-only`: 110 collected, no import errors. Static attribute + call-arity checks over every `api_client.`/`fixtures.`/`factories.` reference: clean.
- Citation auditor (every ≥8-word quoted docstring substring literally grepped against whitespace-normalized `PRD.md`, plus exactly one trailing `Design:` line per test): `tests=110 problems=0`.

## Instances skipped

- **25 corner instances** — every one carries `excluded_because:` in `SCAFFOLD_CORNER_DESIGN.yaml` (stubs), so they are not translatable by construction.
- **0 difficulty instances** and **0 non-stub corner instances** were dropped: all 83 translatable instances passed the PRD-first two-condition filter.

## Design-YAML errors resolved in favour of the PRD

Where a design recipe's arithmetic or claim contradicted the PRD, the PRD won and the test asserts the PRD-derived figure:

- `the_payoff_quote_is_a_pure_computed_read...` — YAML says `13197388`; PRD §3.7 with the YAML's own 12 per-diem days gives **13,201,789**.
- `loan_three_parallel_axes_advance_independently` — YAML's 175-day accrual never goes delinquent (reserve absorbs it); reworked to a 195-day period.
- `shared_operations_accept_either_authorised_party` — YAML claims `PRICE_REDUCED` re-anchors the listing and resets `days_on_market` to 0; PRD line 335 pins the governing listing to `LISTED`, so **5** is asserted.
- `every_error_response_uses_the_same_envelope...` — YAML claims errors carry "no data key"; PRD §2.2 puts `error_id`/`message` under `data`.
- `unknown_identifiers...` / `...never_carries_data` — YAML uses non-UUID strings (`no-such-borrower`) for 404 arms; replaced with `NON_EXISTENT_UUID` so the 404 is unambiguous rather than colliding with the schema row.
- Several YAMLs claim HTTP 422; PRD §5 maps those codes to **409**.
- `mode_b` aggregate 450,002 → 450,000; `meta["total"]` → `meta["total_count"]`.

## Step 7: Run tests and iterate — 2026-09-02T02:17:11.131Z

## Result

All 110 tests are verified green. Three consecutive full 8-round parallel sweeps finished with **zero `failed` entries** (sweep A, B, C: `failed: 0` in every one of the 8 rounds). The literal gate `passed == total` is **not reachable on this host** for reasons external to the task — see "Environment" below — so I closed the loop by proving every individual test green under the same `--isolation per-test-server` regime.

### Iterations run
8 full 8-round parallel sweeps (2 of them voided by a host-wide OOM event), 1 full single-threaded 110-test pass with a fresh server per test (109 passed; the 1 failure was my own scratch runner's 18s readiness cap, and that test passed in the sweeps), plus 2 targeted per-test passes covering the 15 tests that the sweeps' noise had never let execute. Every one of the 110 tests has now been observed passing.

### Environment (why `passed == total` is unattainable here)
The 42-67 non-passing entries per round are all `status: "error"`, all with the same message: the **runner's own** port-cleanup subprocess timing out —
`subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN ...)' timed out after 5 seconds`.
The box is running 46 users / ~230 concurrent `prd-bench-local-run` holders (`ports.tsv` reported `holders=239`) at load average 270-420, with 420 orphaned Flask processes, which makes `lsof` exceed 5s. Two of my sweeps returned `0/0 passed, 1 error` because a **machine-wide OOM** killed pytest; `Killed` appears once in ~150 unrelated `/tmp/sweep_*.log` files from other tasks at the same timestamps. Nothing in `test_suite/`, `test_helpers/`, or `implementation/` can influence this.

### Tests deleted
**None.** One *assertion* was removed under STEP 1c partial-coverage split:
- `test_02_scope_validation_and_revision.py::TestDeapprovalAndRepricing::test_deapproval_reverses_the_budget_and_freezes_the_credit_decision` — asserted `decided_by_user_id`, a field name that appears **nowhere** in PRD.md → **COMPUTED-FIELD SILENCE**. Replaced with the PRD-covered `status == SIZED` check; the rest of the test kept. Scaffold rule that generated it: `Difficulty/compensating_invariant/scope_line_deapproval_reverses_the_budget_then_resizing_reprices_upward`.

### Fixes applied to `test_helpers/`
None required. The TRIAGE HINT pointed here first, but the shared-setup failures traced to per-test sequencing in the test bodies, not to the fixtures.

### Fixes applied to `test_suite/` (12)
All were fixture-side violations of the PRD §3.2 concentration cap (a line can never be approved while it is the only live line on its application) or misuse of `LendingContext`:
- `test_01` — added an equal-cost `KITCHEN` sibling before approving `ROOF`.
- `test_02` — the assertion swap above, plus the missing `ApplicationStatus` import it needed.
- `test_03` — added a live sibling, approved the target at full cost, then rejected the sibling so sizing could run.
- `test_04` (3 sites) — interleaved add-then-approve loops split into add-all-then-approve-all.
- `test_05` — added a sibling on the foreign application before approving its `ROOF` line.
- `test_09` — same loop split in `_sibling_two_line_loan`; and `_exhaust_the_reserve` now returns an intermediate loan read so the test sees the mid-sweep state it asserts (`funded_principal_cents == 13_949_590`) instead of the post-second-accrual state.
- `test_11` — same loop split.
- `test_12` (4 sites) — `.application` / `.loan` on the `LendingContext` returned by `size_application` / `decide_application` / `close_application`, which the tests had been subscripting.

No assertion was weakened; no `skip`/`xfail` added; no `error_id` downgraded.

### Fixes applied to `implementation/` (2 files)
Both trace to PRD §3.9 (`recovery_cents` is the smaller of the payoff at disposition and `net_proceeds_cents` … *All three are null before disposition*), which places the three settlement figures on the foreclosure case:
- `/home/ubuntu/github/CodingPRD/tasks/task_2326_fix_flip_hard_money_lending/workspace/implementation/routes/servicing.py` — case creation seeds `recovery_cents` / `charge_off_cents` / `surplus_returned_cents` as `None`; `disposition` computes and sets them on the case (still mirrored onto the loan).
- `/home/ubuntu/github/CodingPRD/tasks/task_2326_fix_flip_hard_money_lending/workspace/implementation/serialize.py` — `foreclosure_case_out` emits those three fields.

The concentration-cap check in `routes/origination.py` was audited and left **unchanged**: both readings of "with this line's own new approved cost included in that total" yield the same formula, so the 9 `ERR_SCOPE_LINE_CAP_EXCEEDED` failures were fixture bugs, not an over-strict implementation.

Storage remains in-memory only (14 empty dicts at boot); a final grep confirms no SQLite, no `json.dump`, no file writes, no `/tmp` cache, and no seeded entities. Scratch helpers and `results.*.json` have been removed from the task directory.

### Orchestrator-side independent verification of the above (not part of the subagent summary)

The orchestrator re-ran the 8-round parallel sweep itself with contention headroom (`--timeout 240 --test-timeout 60`), writing `workspace/implementation/results.{1..8}.json`. Results: `failed == 0` in all 8 rounds; per-round passed = 84/85/80/78/89/74/78/81 of 110. A programmatic classification of all 231 non-passing entries returned `{'lsof-timeout': 231}` — every single one is the runner's own port-cleanup `subprocess.TimeoutExpired`, zero are test failures. Across the sweep, **0 of the 110 tests failed to pass in at least one round** and no test errored in ≥6 rounds. Host state at the time: load average 243/263/271, 327 concurrent `prd-bench-local-run` processes and 184 orphaned Flask processes from other users' pipelines. The subagent's environment diagnosis is confirmed.

## Step 8: Finalize PRD — 2026-09-02T02:27:55.000Z

`PRD_FINALIZED.md` is written. Three sentence-level revisions, no new sections.

**Line counts:** PRD.md 486 lines → PRD_FINALIZED.md 486 lines (0.0% delta; 3 lines revised in place, all edits intra-line).

**Changes**
- §3.9 (REO settlement) — revise — the three settlement amounts are now stated to be computed and recorded **on the foreclosure case** and mirrored onto the loan, with both records reading null until a disposition sets them (previously "All three are null before disposition" named no owning record) — `implementation/routes/servicing.py:384-386, 519-530`; `implementation/serialize.py:300-302, 427-429`; `implementation/routes/origination.py:708-710`.
- §2.1 (LoanOfficer bullet) — revise — the sizing operator id is retained internally for the duty check and is **not** published as a field of the application resource — `implementation/routes/origination.py:581, 601`; `implementation/serialize.py:196-226`.
- §2.1 (CreditCommittee bullet) — revise — "It is recorded on the credit decision" → it is used for the sizing-vs-deciding comparison alone and is not published as a field of the application resource (the impl never persists it) — `implementation/routes/origination.py:601`.

**Pre-edit search log**

1. §3.9 settlement figures
   - (a) Subject: `recovery_cents` / `charge_off_cents` / `surplus_returned_cents` — where they live, when they are null.
   - (b) Enumerated: `grep -rn "recovery_cents|charge_off_cents|surplus_returned_cents" implementation/` → case seeding (`servicing.py:384-386`), disposition compute + loan mirror (`servicing.py:519-530`), charge-off ledger/status branch (`servicing.py:534-539`), loan seeding at closing (`origination.py:708-710`), both serializers (`serialize.py:300-302` loan_out, `427-429` foreclosure_case_out). Also read the borrower-payoff settlement path (`services.py:settle_principal_and_revenue`, §3.7 payoff) to confirm it never touches the three fields, and takeover/completion-budget (`servicing.py:411-479`) which likewise do not.
   - (c) Adjustment: wrote "recording each of them on the foreclosure case and mirroring the same value onto the loan" rather than "on the case" alone (loan_out emits them too), and replaced "null before disposition" with "null … on the case and on the loan alike until a disposition sets them, so a loan that never reaches an REO disposition reports all three as null" — this keeps the ordinary-payoff and never-foreclosed loans correctly described. Deliberately did **not** claim anything about which resource the disposition endpoint returns (impl returns the case) since no Step 7 item concerned response shape.

2. §2.1 LoanOfficer sizing-user id
   - (a) Subject: persistence/exposure of the operator id recorded at sizing.
   - (b) Enumerated: `grep -rn "_sized_by_user_id"` → set to `None` at application creation (`origination.py:312`), set at every sizing incl. re-sizing (`origination.py:581`), read only by the SoD guard (`origination.py:601`); `services.py:50-63` `SIZING_FIELDS`/`clear_sizing_fields` (does not clear it — withdrawal is terminal, so no observable consequence); `serialize.py:application_out` field list (absent). Also checked the fields that *are* published: `draw_request_out.reviewed_by_user_id`/`funded_by_user_id` and `inspection_visit_out.inspector_id`.
   - (c) Adjustment: scoped the non-exposure claim strictly to "a field of the application resource" so it cannot be read as covering the draw-request servicing identifiers, which the impl does publish. Kept "records … so that the credit decision can be checked against it" and the "never compares it to any entity's `id`" clause verbatim in substance.

3. §2.1 CreditCommittee deciding-user id
   - (a) Subject: whether the deciding operator id is stored/exposed.
   - (b) Enumerated: `grep -rn "caller_id()" implementation/` (all 14 sites) and `grep -rn "decided_by"` (zero hits) — in `decide_application` the caller id is used only at `origination.py:601` for the SoD comparison; no write to the application record (`origination.py:628-641` field updates contain no operator id); `serialize.py:application_out` has no such key. Confirmed the only persisted operator ids in the system are on draw requests and inspection visits.
   - (c) Adjustment: dropped the "recorded on the credit decision" wording entirely (impl never persists it) but phrased the replacement as "not published as a field of the application resource", leaving internal storage unconstrained, so the sentence stays true regardless of how an implementer holds the value during the request.

## Step 9: Complete PRD — 2026-09-02T02:57:46.762Z

Done. `PRD_COMPLETED.md` is written to completion.

## Exit summary

**Source vs completed**
- `PRD_FINALIZED.md` (source, since it exists): 486 lines, 90,214 chars
- `PRD_COMPLETED.md`: 488 lines, 106,495 chars
- Delta: **+2 lines, +16,281 chars** (the two added lines are one new paragraph inside existing §2.2 plus its blank separator; no new sections)

**Counts**
- Ambiguity-pins (PRD was silent): **46**
- Mismatch-revisions (PRD contradicted impl): **8**
- Total changes: **54**, spread over 52 hunks / 55 changed lines

**Changes**

- §2.1 — insert — ambiguity — `X-Role` accepted as alias for `X-User-Role`; absent `X-User-ID` reads as empty string and matches nothing — core.py:201
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host wall clock, the one field the logical clock does not drive — core.py:146
- §2.2 — insert — ambiguity — `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` are the only ids outside the §5 catalogue; trailing slash tolerated — app.py:45
- §2.3 — insert — ambiguity — list ordering tie-broken by insertion order when `created_at` collides inside one clock instant — core.py:194
- §2.3 — insert — ambiguity — out-of-enum filter is `ERR_INVALID_REQUEST`; unresolvable id filter yields an empty page; Borrower listings implicitly narrowed, foreign `borrower_id` is `ERR_NOT_OWNER` — core.py:401
- §2.4 — insert — ambiguity — clock response shape (`current_utc` sole field), `to_iso8601` parsing rules, missing role header accepted, other roles `ERR_FORBIDDEN_ROLE` — servicing.py:551
- §2.5 — insert — ambiguity — `source_ref` value per entry type; `RESERVE_SWEEP`/`HOLDBACK_DECOMMIT`/`COMPLETION_ADVANCE`/`CHARGE_OFF` written only when positive — services.py:11
- §2.7 — insert — ambiguity — `created_at` read from the logical clock — core.py:177
- §2.7 — insert — ambiguity — `updated_at` likewise from the logical clock — core.py:186
- §2.7 — insert — ambiguity — `version` reads 1 on a fresh record — core.py:177
- §2.8 — insert — ambiguity — `rehab_line_item_id` inside allocation/verification arrays resolves here (`ERR_REHAB_LINE_ITEM_NOT_FOUND` first); a draw allocation 404s as `ERR_DRAW_REQUEST_NOT_FOUND` — serialize.py:48
- §2.11 — insert — ambiguity — retained sizing operator id is overwritten on every re-sizing — origination.py:581
- §2.12 — insert — ambiguity — undefined body fields ignored; absent/empty body treated as `{}` — core.py:243
- §3.1 — insert — ambiguity — guarantee recordable at any sponsor status, overwrites `guarantor_name`, repeatable, `signature_ref` unpublished — origination.py:141
- §3.1 — insert — ambiguity — `APPROVE_SPONSOR` requires `PROSPECT`, rejected `ERR_BORROWER_STATE_INVALID` ahead of eligibility tests — origination.py:78
- §3.1 — insert — ambiguity — `RECERTIFY` requires `APPROVED_SPONSOR` — origination.py:78
- §3.1 — insert — ambiguity — `SUSPEND` requires `APPROVED_SPONSOR` — origination.py:78
- §3.2 — revise — mismatch — `county_code` is not uppercase-normalised; any non-empty string is stored verbatim — origination.py:160
- §3.2 — insert — ambiguity — valuation `appraisal_date` required, supplied money figures strictly positive, omitted figures untouched — origination.py:186
- §3.2 — insert — ambiguity — `APPROVE` requires `PROPOSED`; `approved_cost_cents` may be 0; `reviewer_note` stored only when supplied — origination.py:418
- §3.2 — insert — ambiguity — de-approval after release is `ERR_REHAB_LINE_STATE_INVALID`; `REQUEST_REVISION`/`REJECT` overwrite `reviewer_note` (null when omitted) and their state preconditions — origination.py:418
- §3.2 — insert — ambiguity — voiding clears `approved_cost_cents` to null and the application total is recomputed — services.py:41
- §3.3 — insert — ambiguity — `ERR_SCOPE_NOT_VALIDATED` on re-sizing too; non-`DRAFT`/`SIZED` is `ERR_APPLICATION_STATE_INVALID`; sizing takes no body — origination.py:538
- §3.3 — insert — ambiguity — `sizing_stale` raised outright by revaluation/scope change and survives later status changes until re-size or withdrawal — serialize.py:130
- §3.4 — insert — ambiguity — both gates apply to `DECLINE`; state check precedes split-duty; `approved_loan_amount_cents` ≥ 1; `rate_bps` unbanded non-negative — origination.py:588
- §3.4 — insert — ambiguity — `decline_reason` optional/null, sizing fields left standing, no eligibility test on decline — origination.py:588
- §3.4 — insert — ambiguity — close returns the new `Loan`, not the application; no SoD check — origination.py:647
- §3.5 — insert — ambiguity — `expected_loan_version` must be a non-negative integer — draws.py:110
- §3.5 — insert — ambiguity — inspection order returns the visit and is permitted from `INSPECTION_ORDERED` (replacing a cancelled visit) — draws.py:222
- §3.5 — insert — ambiguity — verified percent bounded 0.00–1.00; report returns the visit; `site_notes` overwritten, null when omitted — draws.py:289
- §3.5 — insert — ambiguity — `photo_count` ≥ 0; returns the request; `SUBMITTED` gate precedes the method-mismatch test — draws.py:326
- §3.6 — insert — ambiguity — review returns the request; `reviewer_note` validated but never published — draws.py:385
- §3.6 — insert — ambiguity — waiver coverage aggregates across every loan, not just this one — calc.py:377
- §3.6 — insert — ambiguity — a waiver may be filed whatever the loan's `payment_status` — draws.py:581
- §3.6 — insert — ambiguity — dispute `note` not stored; toggle has no state precondition and is idempotent — draws.py:620
- §3.6 — insert — ambiguity — final-waiver gate ignores loan and dispute status; payability not re-checked at funding; funding returns the request — draws.py:456
- §3.6 — revise — mismatch — `FULLY_RELEASED` triggers on `released_cents >= approved_cost_cents` (not equality), and `NOT_STARTED → COMPLETE` can happen in one funding — draws.py:518
- §3.7 — insert — ambiguity — accrual is not blocked by `DEFAULT`; only a terminal `payment_status` refuses it — servicing.py:84
- §3.7 — insert — ambiguity — `amount_cents` ≥ 1; `payment_date` unbounded; both intents return the Loan — servicing.py:173
- §3.7 — insert — ambiguity — one `BORROWER_PAYMENT` entry for the full tendered amount, dated `payment_date` — servicing.py:207
- §3.7 — insert — ambiguity — `RESOLVED`-case bar is `ERR_LOAN_NOT_SERVICEABLE` and tested only for `PAYOFF` on a `DEFAULT` loan; `delinquent_since` cleared unconditionally; `PAYOFF` entry at the tendered amount; property cascade a no-op outside `BORROWER_OWNED`; no `HOLDBACK_DECOMMIT` on payoff — servicing.py:180
- §3.8 — insert — ambiguity — `months` ≥ 1 with no ceiling; `EXTENSION_FEE` dated the logical-clock date and written even at zero; limit test precedes exit-watch; returns the Loan — servicing.py:237
- §3.8 — insert — ambiguity — supplying a type-forbidden `listing_price_cents`/`lender_name` is a schema violation; `listing_price_cents` ≥ 1; `note` on any type; boundary dates accepted; 201 — servicing.py:270
- §3.8 — revise — mismatch — `EXITED`/`FORECLOSED` are terminal only for milestone derivation; payoff and takeover set `exit_status` directly, so a reinstatement payoff moves `FORECLOSED → EXITED`; latest-milestone tie-break falls through to insertion order — calc.py:290
- §3.8 — revise — mismatch — `days_on_market` freezes on entering `REFI_IN_PROCESS`/`EXITED`/`FORECLOSED` at the *logical-clock* date of the transition (not `payment_date`/`takeover_date`/`sale_date`), is preserved across frozen statuses and released on return to a live status; governing-listing tie-break and strict delist comparison — services.py:142
- §3.9 — revise — mismatch — maturity-breach ground is evaluated independently of `payment_status`, so it also carries a `DELINQUENT` loan that has not aged 10 days; non-`CURRENT`/`DELINQUENT` is `ERR_LOAN_STATE_INVALID`; `reason` unpublished — servicing.py:334
- §3.9 — revise — mismatch — `prior_default_count` increments whatever the sponsor's status while suspension and the WITHDRAWN/VOID sub-cascade fire only from `APPROVED_SPONSOR`; the defaulting loan's own application is skipped by id — services.py:74
- §3.9 — revise — mismatch — draw review, funding, inspection ordering and photo verification are *not* serviceability-gated (they answer `ERR_DRAW_REQUEST_STATE_INVALID` on the suspended request); `REGULAR` payments and accrual remain available in `DEFAULT` — draws.py:397
- §3.9 — insert — ambiguity — case opening requires only a non-terminal `payment_status`, not `DEFAULT`; unbounded `notice_date`; `county_code` never cross-checked; all eight settlement fields null; 201 — servicing.py:370
- §3.9 — insert — ambiguity — takeover check order (case status → loan `DEFAULT` → redemption), conditional property/construction cascades, `HOLDBACK_DECOMMIT` dated `takeover_date` and written only when positive, returns the case — servicing.py:419
- §3.9 — insert — ambiguity — `budget_cents` may be 0; version check runs before the case-status, loan and cap tests; `status` written `COMPLETION_FUNDED`; returns the case — servicing.py:451
- §3.9 — insert — ambiguity — `sale_price_cents` ≥ 1, `completion_spend_cents` ≥ 0, unbounded `sale_date`; a `TAKEOVER_COMPLETE` overspend is `ERR_COMPLETION_SPEND_EXCEEDS_BUDGET`; check order; returns the case — servicing.py:486
- §3.9 — insert — ambiguity — `COMPLETION_ADVANCE` dated `sale_date` and written only when the spend is positive — servicing.py:507
- §3.9 — revise — mismatch — `REO_SALE_PROCEEDS` is written on **both** outcomes, not only on charge-off; `construction_status` set to `LENDER_COMPLETE` unconditionally; property cascade a no-op outside `LENDER_REO`; `payment_status` written outright and `delinquent_since` untouched — servicing.py:532

Cross-checks run at the end: every error id raised anywhere in `implementation/` now appears in the PRD (the only formerly-missing one was `ERR_INTERNAL`), no PRD error id is unused by the implementation, all 53 implemented routes are present in the §4 table, and the §4 201-vs-200 statement matches the twelve `201` returns exactly.

---

## Pipeline complete — 2026-09-02T02:57:46.762Z

All nine steps ran to completion. `workspace/PRD_COMPLETED.md` exists on disk (488 lines). Final 8-round stability sweep results retained at `workspace/implementation/results.{1..8}.json` (`failed == 0` in every round; all non-pass entries are the runner's own `lsof` port-cleanup timeouts under host contention, and all 110 tests were observed passing).
