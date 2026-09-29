# Worklog — task_2412_season_pass_blockout_administration

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2412_season_pass_blockout_administration` and its `workspace/` subdirectory. Index 2412 was pre-assigned by the invoking pipeline (no scan of ./tasks/, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate scaffold — 2026-09-02T17:12:08.157Z

All three artifacts are complete and the linter is clean.

Verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2412_season_pass_blockout_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2412_season_pass_blockout_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2412_season_pass_blockout_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  1013

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2412_season_pass_blockout_administration/SCAFFOLD.yaml` (1772 lines, §1.0–§1.7, neither design key present)
- `/home/ubuntu/github/CodingPRD/tasks/task_2412_season_pass_blockout_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1496 lines, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2412_season_pass_blockout_administration/SCAFFOLD_CORNER_DESIGN.yaml` (4347 lines, single key `scaffold_corner_design`)

## Scaffold counts

`domain_name: season-pass-blockout`, `api_prefix: ""`, difficulty `beyond_expert`. complexity_profile: primary `pricing_engine`, secondary `quota_allocation`, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`, topology `graph`, shape `parallel`, role_model `segregation_of_duties`, consistency `immediate`.

- Entities: 12 (PassProgram, PassTier, ParkDay, BlockoutAssignment, Passholder, SeasonPass, PaymentPlan, Installment, Reservation, Visit, SharingCase, UpgradeOrder)
- State machines: 12; concurrency rules: 2 (`plan-create-stale-pass`, `blockout-create-stale-park-day`)
- Calculations: 8 (2 dual-variant: `upgrade_credit`, `pass_sharing_risk_score`)
- Validations: 62, strictly ascending priorities
- Endpoints: 54; error codes: 59; roles: 5 (ProgramAdmin, PassOfficeClerk, GateAgent, ComplianceOfficer, Passholder)

## Design instance counts

- §1.8: 18 instances, 2 per each of the 9 Difficulty Rules
- §1.9: all 9 sections present, 71 test-recipe instances + 18 `excluded_because` stubs — entities 11+2, state_machines 12+4, calculations 7+7, validations 11+3, endpoints 6, errors 14, rbac 6, cross-cutting complexity layers 3+2, consistency model 1

## Verification beyond lint

All 59 catalog error codes are triggered somewhere in the two design files (0 uncovered, 0 invented codes). Instance names are unique across the union of both files. Every stub's cited `difficulty_instance` resolves to a real §1.8 instance. No forbidden concurrency vocabulary in any file.

## Design adjudications

1. **`ERR_PHOTO_NOT_CAPTURED` renumbered 60 → 39.** At priority 60 it was permanently shadowed by priority 46 `ERR_PASS_NOT_ACTIVE` (an unprocessed pass is always non-ACTIVE), making the code untriggerable. Moved ahead of 40 with an explanatory note; `Visit.entry_at` became `source: input` and `photo_match` defaults to `NOT_CHECKED` so the gate corner tests are deterministic.
2. **Priority 41 (`ERR_PROGRAM_STATUS_INVALID`) pinned per endpoint.** The original condition ("not one of the statuses the endpoint requires") left recipes ambiguous; added a `note:` enumerating required statuses for each of the six guarded endpoints, and stating that the two blockout endpoints are deliberately unguarded (the calendar is editable in any non-CLOSED status).
3. **Deliberate priority orderings exercised in §1.9:** 11 before 12 (tier before park-day existence), 18 before 85 (visit existence before evidence validity), 39 before 46, 42 before 49 (program-renewal state beats pass-renewable state), 61 before 71 (transfer freeze beats date mismatch), 31 before 82 and 30 before 90/91 (stale-version before uniqueness/bounds), 100 before 101 (day capacity before window capacity), 3 before 4 (role before schema).
4. **Structural choices:** `BlockoutAssignment` is the `graph`-topology junction (tier × park day) and is exercised from both sides; `SeasonPass` carries the `parallel` shape as two independent dimensions (`pass_status` / `billing_status`); `SharingCase` carries the `cyclic` shape with a single permitted appeal (`review_round` capped at 2); `POST /_clock/set_current_utc` (default 2026-08-01T00:00:00Z) supplies the logical clock that makes the trailing-7-day sharing window and the billing `as_of_date` sweeps deterministic.

## Step 3: Copy shared files — 2026-09-02T17:12:08.157Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:27:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md`

**Final line count: 510.** Last heading: `## 5. Error Code Catalogue` (line 446). File terminates at a complete table row (`| ERR_CURE_AMOUNT_MISMATCH | 422 |`) — a real section boundary, not mid-sentence or mid-table.

Orchestrator anti-truncation check (independent of the subagent): `tail -12` shows the error catalogue's final rows intact; `grep -c '^| `ERR'` = 59 rows, matching the scaffold's 59 declared error codes. No regeneration needed.

**Section list (26 headings):** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Record Properties, 2.5 The Logical Season Clock, 2.6 Cascades/Reconciliation/Derived Counters, 2.7 Stale-Read Protection, 2.8 Validation Precedence, 2.9 Money/Counts/Rounding, 2.10 The Pass Ledger Identity, 2.11 Programme Status Gating); §3 Business Logic & Workflows (3.1 Programmes and Tiers, 3.2 Operating Calendar, 3.3 Selling and Processing a Pass, 3.4 Payment Plans and Installments, 3.5 Monthly Billing Run, 3.6 Reserving a Crowded Day, 3.7 The Turnstile, 3.8 Sharing Cases, 3.9 Upgrades/Renewals/Season Reporting); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Coverage confirmation**
- Endpoints: 54/54 rows in the §4 table, including `/_clock/set_current_utc`.
- Validations: 62/62 expressed — the 62 conditions collapse to 59 distinct `error_id`s, all stated in prose with triggering condition; precedence given as ordered bands in §2.8 plus per-endpoint check orders in §3.3–§3.9.
- Error codes: 59/59 in the §5 table with HTTP status, each also referenced in §2/§3 narrative.
- Calculations: 8/8 in precise prose: `payment_plan_amortization`, `delinquency_evaluation`, `park_day_capacity_posture`, `pass_sharing_risk_score` (GATE_CLUSTER / ROLLING_WINDOW), `upgrade_credit` (PAID_TO_DATE / PRORATED_VALUE) plus `upgrade_settlement_total`'s six pinned steps, `renewal_quote`, `program_revenue_analysis`.
- State machines: 12/12, all 56 transitions narrated, including SeasonPass's parallel `pass_status` (9) x `billing_status` (8).
- Roles: 5/5 with the entity-backed `Passholder` self-scoping rule.

**Hard Contract 1 — Field-Name Coverage: PASS** (entity fields 127/127; endpoint inputs 134/134; inline computed outputs 22/22; path params 12/12; 405 distinct backticked tokens matched with fenced blocks stripped).

**Hard Contract 2 — Rule Coverage: PASS** (2/2 concurrency rules with OCC field + error + status named; 12/12 state machines, 56/56 transitions; 8/8 calculations; 62/62 validation conditions traceable to an error ID; all side_effects, applies_to scopes, enum domains, and sibling-branch symmetry documented).

**Hard Contract 3 — §3 Path Purity: PASS** (1073 backtick tokens in §3: 0 paths, 0 bare HTTP methods, 0 method+path combos; routing confined to §4).

**Constraints honoured:** neither design YAML was opened, grepped, or referenced; no sibling task directory was read.

**Two scaffold inconsistencies handled without inventing behaviour:** (1) `SharingCase.risk_score_at_open` — field description points at ROLLING_WINDOW while the endpoint side effect assigns `Passholder.sharing_risk_score`; prose satisfies both readings. (2) `PassTier.peak_reservation_quota` — field description scopes to park days on/after the clock date while validation scopes to PEAK/CAPACITY_LOCKED days; prose combines both conditions. Additionally the payment-plan precondition `payment_mode == PAYMENT_PLAN` has no error code anywhere in the scaffold, so it is stated as a precondition without a fabricated code.

## Step 6: Generate implementation — 2026-09-02T18:11:00.000Z

(Steps 5 and 6 ran concurrently; Step 6 returned first, so its entry is recorded first. Step 5's entry follows below.)

Implementation is complete and verified end-to-end.

## Files written — `tasks/task_2412_season_pass_blockout_administration/workspace/implementation/` (3,004 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Guarded launcher (`import flask` probe, then `exec python3 app.py`), binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `Flask>=3.0.0` |
| `app.py` | 69 | App factory, blueprint wiring, per-request unit-of-work opener, `ApiError`/`HTTPException`/`Exception` envelope handlers, `SerializedApp` RLock WSGI wrapper |
| `db.py` | 167 | In-memory dict store, logical clock (default `2026-08-01T00:00:00Z`), monotonic ms stamps, `insert`, month-clamping `add_months`, snapshot-diff `begin`/`commit`/`force_touch` |
| `errors.py` | 87 | All 59 error codes with HTTP statuses + `ApiError` |
| `response.py` | 59 | `meta`/`response_type`/`data` envelopes, `req_`+20-char ids, pagination meta |
| `middleware.py` | 43 | `X-User-ID`/`X-User-Role` auth then per-endpoint RBAC |
| `validate.py` | 187 | Declarative body specs (unknown/missing/type/format/range/enum/decimal-places), pagination and query-filter validation |
| `serializers.py` | 228 | Per-entity output with computed fields; capture function for the version diff |
| `services/calc.py` | 138 | All pinned constants, `derive_posture`, `amortize`, `upgrade_settlement`, renewal pricing, risk weights, ROUND_HALF_UP/ROUND_FLOOR Decimal helpers |
| `services/domain.py` | 451 | Existence lookups (correct 404 per type), derived counters, all cascades (capacity lock/release, revocation, restore, expiry, risk rescoring, auto-case) |
| `services/billing.py` | 97 | Billing run: ordered missed sweep, delinquency ladder, reservation date-split sweep, quote expiry, 7 counters |
| `routes/programs.py` | 151 | Programmes, lifecycle advance, billing runs, revenue summary |
| `routes/catalog.py` | 317 | Tiers, park days + forecast, blockout assignments + lift, passholders |
| `routes/passes.py` | 382 | Season passes, process, payment plans, installments, settle, reinstate, renewal quote/renew |
| `routes/park_ops.py` | 304 | Reservations (13-step ladder), visits (9-guard ladder), cancel, close |
| `routes/compliance.py` | 313 | Sharing cases (open/review/decide/appeal), upgrade orders (quote/apply/reverse), `POST /_clock/set_current_utc` |

## Coverage verified by machine check
- **Endpoints:** all 54 PRD §4 rows present, no extras; the full 5-role x 54-endpoint authorisation matrix matches the PRD table exactly (script-diffed against the PRD table).
- **Errors:** 59/59 codes present with byte-identical names and HTTP statuses; no missing, no extra, no status mismatch.
- **Existence:** all 12 `*_NOT_FOUND` codes returned in the §2.8 global resolution order, for path vars and body FKs (verified `program -> tier -> passholder` chain on the sale payload).
- **Calculations verified against every PRD worked example:** posture (40/36 -> `0.9000`, PEAK, 4 slots, 2 windows; 1000/975 -> CAPACITY_LOCKED + 2 installed blockouts), amortisation (25500 -> 3643x6 + 3642; 10500 -> 2625x4; Jan-31 -> Feb-28 clamp), upgrade `PAID_TO_DATE` (25000/24215/24215/785/0/**785**), `PRORATED_VALUE` (3-of-4 days -> `0.7500` -> 9000 raw, 1000 fee, 10000 due), renewal (30000 -> 25500 -> credit 1500 -> **24000**; post-deadline -> 28500), risk gate-cluster **65** vs rolling-window **35** with auto-case at threshold 65, revenue summary's nine figures cross-checked against the four PRD sets.
- **State machines / cascades exercised:** programme ladder incl. the `SEASON_ACTIVE -> CLOSED` shortcut and its expiry cascade; tier publish/retire refusals; bidirectional day-class flips (lock installs blockouts + cancels reservations; release lifts only `CAPACITY_ADJUSTED` with `CAPACITY_RELEASED`, reservations not restored); plan `ACTIVE -> SUPERSEDED/COMPLETED/TERMINATED_ON_REVOCATION`; installment cure cycle and `VOIDED -> SCHEDULED` restore; billing-run date split (past -> `NO_SHOW`, future-on-suspended -> `CANCELLED_BY_SUSPENSION`); waive-cure ledger effect; case `OPEN -> UNDER_REVIEW -> SUBSTANTIATED -> APPEAL_PENDING -> UNDER_REVIEW -> DISMISSED` with exact forfeit/restore compensation; two substantiated cases -> holder `BANNED`; upgrade apply/reverse with the §2.10 identity holding exactly at every step.
- **Precedence spot-checks:** 401 before 403 before 400 before 404 before ownership/SoD before OCC 412 before `ERR_PHOTO_NOT_CAPTURED` before state before hold/anti-passback before temporal before referential before constraint before fiscal — including anti-passback closed at exactly 90 minutes, and `ERR_INVALID_CASE_STATE` correctly shadowing `ERR_APPEAL_LIMIT_REACHED`.
- **Runtime:** boots via `bash start.sh` in ~1s, three consecutive kill-and-relaunch cycles each answered with **zero** records (no seeding, no persistence, in-memory dicts only); malformed JSON, unknown route and wrong method all return proper envelopes. Stray test server cleaned up (other tasks' servers left untouched).

**One real bug found and fixed:** `routes/compliance.py` had lost its `parse_instant` import in the earlier unused-import trim, which would have made `POST /_clock/set_current_utc` raise `NameError` on every call. Re-added and re-verified with pyflakes (no undefined names anywhere in the tree).

## Interpretation decisions (PRD ambiguities)
(a) version/`updated_at` bumping is implemented as a per-request serialize-and-diff commit, so cascaded ParkDay/SeasonPass/PassProgram/Passholder records bump automatically, at most once per record per request, with explicit force-touch for re-forecast, manual blockout creation, programme advance, tier status change and blockout lift; (b) `created_at`/`updated_at` come from a monotonic wall clock, the logical clock is used only where the PRD names it; (c) client-supplied instants (`entry_at`, `paid_at` -> `settled_at`, `to_iso8601` -> `current_utc`, and the clock echo reused for `quoted_at`/`settled_at`) are echoed verbatim, while server-computed instants (`quote_expires_at`, `created_at`, `updated_at`) use canonical 3-digit-ms form; (d) `discount_applied_pct` is snapshotted at entry and `spend_cents` stored verbatim (no server-side discount arithmetic); (e) `GET /visits` orders by `entry_at ASC, created_at ASC`; (f) `POST /season-passes/{pass_id}/process` enforces `ERR_PROGRAM_STATUS_INVALID` per §2.11; (g) arrival-window 08:00/22:00 bounds are schema-band 400, `end <= start` is 422; (h) `installment_count` out of range is the dedicated 422, not 400; (i) uniqueness violations (tier name/rank, park-day date, holder email) map to `ERR_INVALID_REQUEST` 400 checked after the state/referential guards; (j) renewal pricing uses the target tier's programme early-bird deadline; (k) `credited_amount_cents` and `forfeited_revenue_cents` are computed from APPLIED orders / REVOKED passes so reversal and dismissal compensation is exact by construction; (l) billing-run counters count the transitions that run performed; (m) auto-opened cases carry `evidence_visit_ids: []` and `note: null`; (n) suspension releases only reservations on days >= `as_of_date`; (o) Passholder self-filtering applies only to `GET /season-passes`, with ownership 403 limited to the endpoints named at priority 25.

## Step 5: Generate unit tests — 2026-09-02T19:31:00.000Z

Stage 2 is complete. Every live design instance in both queues is now translated, and both audits pass clean.

## Files written this session
- `test_suite/test_14_error_catalogue.py` — new, 25 tests, the 14 live `errors` instances
- `test_suite/test_15_identity_and_authorization.py` — new, 12 tests, the 6 `rbac` instances
- `test_suite/test_16_concurrency_and_consistency.py` — new, 8 tests, the 3 live `cross-cutting complexity layers` instances + the 1 `consistency model` instance
- `test_suite/test_04_passholders_and_pass_sales.py` and `test_06_payment_plans_and_installments.py` — quote repairs only (two citations had been truncated mid-sentence with an added full stop, so they failed literal grep; both extended to the full PRD sentence)

Earlier in the same assignment: `test_helpers/*` (Stage 1, 8 modules) and `test_suite/test_01`...`test_13`, plus the `fixtures.py` fix that gives a programme an operating day before `SALES_OPEN -> SEASON_ACTIVE` (PRD §3.1 precondition that `build_program(status=SEASON_ACTIVE)` was previously violating at ~37 call sites).

## Totals
- 16 files, 82 classes, **157 test functions** (159 pytest items — one test is parametrised x3)
- Queue A (Difficulty): **39 tests / 18 of 18 instances**, every instance >= 2 tests
- Queue B (Corner): **118 tests / 71 of 71 live instances** — errors 25, validations 22, state_machines 15, calculations 13, endpoints 12, rbac 12, entities 11, cross-cutting 6, consistency 2
- **0 instances skipped.** All 18 `excluded_because:` corner stubs are untouched (no test tags any of them).

## Audit results
- PRD-quote sweep: every `PRD: "..."` docstring citation survives whitespace-normalised literal grep against `workspace/PRD.md` — **0 failures**
- `Design:`-tag sweep (AST): 157/157 tests tagged, tag is the last docstring line, **0 untagged, 0 dual-tagged, 0 tags pointing at a non-existent or stub instance**; cross-checked against the parsed yamls (71 corner live + 18 difficulty live + 18 stubs enumerated)
- `py_compile` clean on all 16 test files and all helper modules; no duplicate test or class names; static arity/name check of every `api.*` call and every `test_helpers` call against the real signatures — 0 problems
- Tags for the last two sections carry the yaml's literal section names, which contain spaces: `Design: Corner/cross-cutting complexity layers/...` and `Design: Corner/consistency model/...`

## Yaml recipes intentionally narrowed (PRD does not publish the field/value)
Assertions dropped or replaced with the PRD's real field name, per the two-condition filter: `assignment_source` -> `source`; `lifted_at` (no such field); `booked_by_role` (absent from the PRD); `credited_total_cents` -> `credited_amount_cents`; `data.message == 'Payment plan not found'` (the PRD publishes no catalogue messages, so only the envelope shape is asserted); the difficulty 85 %-threshold recipe's `DESIGN -> SALES_OPEN` without a `PUBLISHED` tier. No test was weakened beyond dropping these unsupported clauses.

I did not read `workspace/implementation/` or any sibling `task_*/` directory, and I did not run pytest against the concurrently-generated implementation — all verification here is static.

## Step 7: Run tests and iterate — 2026-09-02T19:55:00.000Z

All 8 parallel rounds are green: 159/159 in every round.

## Summary

**Iterations run:** 2 sweeps (iteration 1 diagnosed, iteration 2 verified green). One extra single-round diagnostic run was needed because the first 8-round sweep produced no usable results.

**Sweep-infrastructure note (not a task defect):** the first 8-round sweep returned `total: 0, errors: 1` for all 8 rounds — every round's pytest died at ~62% within a 30 ms window, so no `junitxml` was written and the runner reported a bare run-level error. The server logs ended in `Killed` (the runner's own normal per-test teardown), never `Terminated`, memory was at 15/123 GB with load 15 on 32 cores, and a subsequent single round under `setsid` completed all 159 tests and wrote full failure detail. The re-run 8-round sweep under `setsid` also completed all 8 rounds cleanly. Conclusion: a transient host event, not reaping and not an implementation fault. Failure detail for iteration 1 was therefore taken from the single-round `results.single.json` plus the union of `FAILED` lines across all 8 rounds of `sweep.log` (the union matched exactly).

**Tests deleted:** none. Every failing test passed STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability); all 71 failures were test-artifact defects, not PRD-silence.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_errors.py` — `ApiErrorId`: added a post-class alias loop (`setattr(ApiErrorId, member.value, member)`). 70 of the 71 failures were `AttributeError: type object 'ApiErrorId' has no attribute 'ERR_*'`: the enum declared members under short names (`UNAUTHENTICATED = "ERR_UNAUTHENTICATED"`) while the suite referenced both spellings — 59 distinct `ApiErrorId.ERR_*` references and 59 distinct short-name references. Aliasing makes both spellings resolve to the same member without changing a single wire value, so no `error_id` assertion was weakened.

**Fixes applied to `test_suite/`:**
- `test_16_concurrency_and_consistency.py` (`TestThePlanVersionGuardCatchesAStaleRead::test_the_fresh_version_enrols_and_is_itself_consumed`) and `test_14_error_catalogue.py` (line 872) — renamed the asserted payment-plan field `installment_amount_cents` -> `monthly_amount_cents`. The token `installment_amount_cents` does not occur anywhere in `workspace/PRD.md`; PRD §3 names the field verbatim: "`monthly_amount_cents` is `financed_amount_cents` divided by `installment_count`, rounded half up to a whole number of cents." A mis-translated field name is a STEP 2 test bug, and `test_06_payment_plans_and_installments.py` already used the correct PRD spelling. The asserted values (2625 and 2775) were verified correct against the PRD amortisation stages and were left untouched.

**Fixes applied to `implementation/`:** none. No implementation defect survived diagnosis; the implementation already exposed `monthly_amount_cents` (`workspace/implementation/serializers.py:124`) and returned the full PRD error catalogue.

**Final sweep:** `results.1.json` ... `results.8.json` in `workspace/implementation/`, each `159 total / 159 passed / 0 failed / 0 errors`. No stray servers left behind; diagnostic per-round logs removed.

**Orchestrator independent verification (per prior-session lesson that a Step 7 subagent can claim a clean sweep without leaving artifacts):** all 8 `results.N.json` exist on disk (~52 KB each, same mtime 19:29) and parse; every one reports total=159, passed=159, failed=0, errors=0. Confirmed, not taken on trust.

**Step 8 skip decision:** Step 7 applied 0 `implementation/` fixes and 0 deletions, but it DID apply 1 `test_helpers/` fix and 2 `test_suite/` fixes, so the strict skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is not met. Step 8 therefore runs, with those three fix sites as its focus list.

## Step 8: Finalize PRD — 2026-09-02T20:00:00.000Z

`workspace/PRD_FINALIZED.md` created. Correct minimal patch is **zero edits** — both `<step_7_diff>` items are test-artifact defects with no PRD-silence and no PRD/impl divergence.

## Summary

**Line counts:** PRD.md 510 lines -> PRD_FINALIZED.md 510 lines, **0.00% delta** (byte-identical, md5 `5b98a379e1d2631c45b4acb392be49c4` on both).

**Changes:** none.

### Per-item adjudication (why each `<step_7_diff>` item produced no edit)

**Item 1 — `test_helpers/api_errors.py` `ApiErrorId` alias loop**
- (a) Subject: the wire spelling of `error_id` values in the error envelope.
- (b) Impl paths enumerated: `implementation/errors.py` (the full catalogue definition), plus every `raise ApiError("ERR_*")` callsite across `routes/{passes,programs,park_ops,catalog,compliance}.py`, `middleware.py`, `validate.py`, `response.py`. Verified by extracting all `ERR_[A-Z_]*` tokens from `implementation/errors.py` and diffing against all such tokens in `PRD.md`: **identical sets, 59 codes each**, so §5's catalogue and §2/§3's trigger prose already pin every wire value the implementation emits.
- (c) No wording adjustment needed. The fix was entirely inside the test helper's Python attribute namespace (short member name vs. `ERR_*` value); it changed no wire value and revealed no PRD gap. The `ApiErrorId` enum is a test-suite construct with no counterpart in `implementation/`, so there is nothing in the PRD for it to pin.

**Item 2 — `test_suite/` rename `installment_amount_cents` -> `monthly_amount_cents`**
- (a) Subject: the name and value of the level-payment field on the payment-plan record.
- (b) Impl paths enumerated: `implementation/serializers.py:114-128` (`plan_out`, the sole payment-plan response shape, used by create/list/read alike via `TABLE_SERIALIZERS`); `implementation/routes/passes.py:174-201` (`create_plan`, the only writer of the field, covering both PRD §3.4 enrolment shapes — first enrolment and re-amortisation); `implementation/routes/passes.py:187-196` (installment schedule generation, which consumes `monthly`/`final`); `implementation/services/calc.py:78-82` (`amortize`, the only producer). Grepped the whole of `implementation/` for `monthly_amount_cents`, `financed_amount_cents` and `final_installment_cents` — six hits total, all in the two files above; no parallel or alternate spelling exists anywhere, including paths Step 7 never exercised (list/read endpoints, the re-amortisation branch, `capture_all`'s mutation snapshot).
- (c) No wording adjustment needed. PRD §3.4 stage two already names `monthly_amount_cents` verbatim, and §3.4's three stages match `calc.amortize` exactly (`financed = outstanding - down + 1500`; `monthly = half_up(financed / count)`; `final = financed - monthly x (count - 1)`), so both asserted values (2625, 2775) are uniquely derivable from existing prose. §4's `/payment-plans/{plan_id}` row ("amortisation figures and counters") plus §3.4 already cover every field `plan_out` emits. The token `installment_amount_cents` appears nowhere in the PRD or the implementation — it was a mistranslation in two test files only.

### Note
The sweep-infrastructure event described in `<step_7_diff>` (first 8-round sweep returning `total: 0, errors: 1`) carries no PRD implication; it matches the known runner-contention pattern rather than any implementation behavior. Consistent with that diagnosis, `implementation/` still holds `results.1.json` through `results.8.json` from the completed verification sweep.

## Step 9: Complete PRD — 2026-09-02T20:12:00.000Z

`PRD_COMPLETED.md` is written. Summary:

**Source vs output**: `PRD_FINALIZED.md` (identical to `PRD.md`) 510 lines / 103,946 chars -> `PRD_COMPLETED.md` 513 lines / 114,270 chars. **Char delta: +10,324.** 28 diff hunks, all in-paragraph inserts/revisions; no new sections.

**Counts: 26 ambiguity-pins, 4 mismatch-revisions.**

- §2.1 Ownership — insert — ambiguity — pinned that ownership scoping stops at the four named writes plus the season-pass listing; a `Passholder` reading reservation/visit/plan/installment/case/upgrade-order collections or single records, or any passholder, sees everything unfiltered — `routes/passes.py:107`, `routes/park_ops.py:147`
- §2.3 Pagination — insert — ambiguity — empty query-param value treated as omitted, undeclared params ignored, identifier filters matched literally and never existence-checked — `validate.py:164`
- §2.3 Ordering — revise — mismatch — visits moved out of the `created_at` default into their own bullet: `entry_at` ascending then `created_at` ascending (also reconciles the "six collections" count and the §4 row) — `routes/park_ops.py:284`
- §2.4 Common properties — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` minted from the host wall clock, not the logical clock, strictly increasing; a record inserted this request stays at `version` 1 — `db.py:106`, `db.py:157`
- §2.5 Logical clock — insert — ambiguity — `current_utc` echoed byte-for-byte; clock-written fields (`settled_at`, `quoted_at`, and a supplied `paid_at`) stored verbatim, server-derived `quote_expires_at` canonical 3-digit; pre-set spelling `2026-08-01T00:00:00.000Z`; clock set bumps no version — `routes/compliance.py:312`, `routes/passes.py:313`, `routes/compliance.py:216`
- §2.8 band 3 — insert — ambiguity — JSON `null` treated as omitted (optional->default, required->rejected), bodyless request = empty object, and the three uniqueness collisions (tier `name`/`tier_rank`, park-day `calendar_date`, passholder `email`) yield `ERR_INVALID_REQUEST` but are evaluated after the existence and state bands — `validate.py:132`, `routes/catalog.py:48`
- §2.9 Rounding — insert — ambiguity — `forecast_utilization_pct` and `visits_per_active_pass` rendered as bare JSON numbers with trailing zeros dropped (`0.9`, `1.0`, `2.0`, `0.0`) — `services/calc.py:69`, `services/calc.py:132`
- §2.11 Programme gating — insert — ambiguity — added the re-forecast bullet and closed the list exhaustively: every other operation can never answer `ERR_PROGRAM_STATUS_INVALID` (billing run, settle, reinstate, renewal quote, upgrade apply/reverse, cancel, visit close, all case actions) — `routes/programs.py:130`, `routes/catalog.py:191`
- §3.1 Programme knobs — insert — ambiguity — `capacity_lock_blockout_max_rank` and `sharing_case_auto_open_score` >= 0 with no ceiling, `season_year` any integer, all bracket/range violations are `ERR_INVALID_REQUEST`, capacity bracket checked before delinquency bracket — `routes/programs.py:31`, `routes/programs.py:46`
- §3.1 Tier status — revise — ambiguity — only the *target* tier is status-checked on an upgrade quote; programme collection filterable on `status`/`season_year`, tier collection on `program_id`/`status` — `routes/compliance.py:178`, `routes/programs.py:76`, `routes/catalog.py:70`
- §3.2 Capacity posture — insert — ambiguity — the floor of 1 on `window_slot_capacity` is unconditional, so a day with `reservation_slot_capacity` 0 still reports 1 — `services/calc.py:68`
- §3.2 Capacity posture — insert — ambiguity — a day born already `CAPACITY_LOCKED` runs the level-one blockout install cascade inside the create request — `routes/catalog.py:155`
- §3.2 Blockout create — insert — ambiguity — the tier's own `status` is not inspected, and a `CAPACITY_LOCKED` day still accepts new manual blockouts though it refuses to release any — `routes/catalog.py:203`
- §3.2 Blockout lift — revise — ambiguity — `reason` is a required string field — `routes/catalog.py:262`
- §3.3 Processing — insert — ambiguity — `photo_hash` and `government_id_last4` are required strings with no shape/length/numeric validation — `routes/passes.py:125`
- §3.4 Enrolment guards — revise — **mismatch** — enrolment inspects neither `payment_mode` nor `billing_status`; the two shapes are distinguished purely by whether an `ACTIVE` plan already exists (PRD had gated shape one on `PAYMENT_PLAN` + `UNBILLED`) — `routes/passes.py:154`
- §3.5 Billing run sweeps — insert — ambiguity — installment pass and both sweeps scoped to the programme's own park days / own passes' upgrade orders — `services/billing.py:58`, `services/billing.py:83`
- §3.5 Billing run report — insert — ambiguity — response `data` is the bare seven-field report, and the three pass counts count distinct passes *this run* moved (never re-counted, never counted when not `ACTIVE`) — `services/billing.py:38`, `services/billing.py:89`
- §3.5 Reinstatement — insert — ambiguity — only active-plan membership is tested on `waive_installment_id` (no-plan case also 404s); naming a non-`MISSED` installment still subtracts from the cure amount but waives nothing and leaves `billed_total_cents` untouched — `routes/passes.py:236`
- §3.7 Anti-passback — revise — ambiguity — closed at both ends (a prior visit at exactly the requested instant violates), one-directional, and park-day-agnostic — `routes/park_ops.py:214`
- §3.7 Gate entry effects — revise — **mismatch** — `discount_applied_pct` is snapshotted at entry (already present on an `OPEN` visit), window bounds compared against the UTC hour/minute of `entry_at`, earliest-created match wins — `routes/park_ops.py:247`, `routes/park_ops.py:250`
- §3.7 Closing a visit — revise — **mismatch** — close stores `spend_cents` (>= 0) exactly as tendered and applies no discount arithmetic; the snapshot no longer happens here — `routes/park_ops.py:297`
- §3.7 Auto-opened case — insert — ambiguity — system case carries `review_round` 0, empty `evidence_visit_ids`, null `note` — `services/domain.py:395`
- §3.8 Opening a case — insert — ambiguity — `note` required; no `pass_status` check and no duplicate-open-case guard (that restraint is the auto-open path's only) — `routes/compliance.py:44`
- §3.9 Upgrade reversal — insert — ambiguity — `payment_amount_cents` retained rather than cleared; no programme-status or `pass_status` check — `routes/compliance.py:293`
- §3.9 Renewal quote guards — revise — ambiguity — `target_tier_id` is a query parameter resolved before the path `pass_id`; renewability is the only guard, with no programme-status and no `PUBLISHED` requirement — `routes/passes.py:329`
- §3.9 Early bird — revise — ambiguity — `early_bird_deadline` read from the *target tier's* owning programme — `services/domain.py:415`
- §3.9 Quote response — insert — ambiguity — response is seven fields (the five figures plus `season_pass_id` and `target_tier_id`), with no raw retention figure — `routes/passes.py:342`
- §3.9 Renewal execution — insert — ambiguity — the duplicate-live-pass guard of §3.3 does not apply; the four listed checks are the whole guard — `routes/passes.py:353`
- §3.9 Season reporting — insert — ambiguity — the analysis response carries `program_id` alongside the nine figures and nothing further — `routes/programs.py:140`

**Orchestrator verification:** `workspace/PRD_COMPLETED.md` exists at 513 lines and ends at the complete §5 error-catalogue table (final row `| ERR_CURE_AMOUNT_MISMATCH | 422 |`) — no truncation. Step 9 edited only PRD prose, so the verified 8/8 green sweep in `workspace/implementation/results.{1..8}.json` remains valid. Pipeline complete.
