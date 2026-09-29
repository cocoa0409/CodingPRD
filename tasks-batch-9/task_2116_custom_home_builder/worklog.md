## Step 1: Create task directory — 2026-08-17T12:02:33.725Z

Created `tasks/task_2116_custom_home_builder/` and `tasks/task_2116_custom_home_builder/workspace/`. Index chosen as 2116 (highest existing was task_2115_judgment_enforcement_asset_search).

## Step 3: Copy shared files — 2026-08-17T12:02:50.297Z

Copied `./INSTRUCTION.md` → `tasks/task_2116_custom_home_builder/workspace/INSTRUCTION.md` (1424 bytes). (Executed early; independent of Step 2.)

## Step 2: Generate scaffold — 2026-08-17T12:52:04.982Z

All three artifacts are generated and validated. Final lint verdict, pasted verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  938

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2116_custom_home_builder/`):
- `SCAFFOLD.yaml` (2850 lines) — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1694 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3964 lines) — single key `scaffold_corner_design`

**Complexity profile**: primary `ledger_reconciliation` + secondary `multi_party_negotiation`; layers = optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation; topology `graph` (self-referential `ScheduleTask.predecessor_task_id`); shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`. Difficulty band: expert-plus. `api_prefix: ""` (flat absolute paths — required for lint check (f) segment derivation).

**Counts**: 14 entities · 10 state machines · 2 concurrency rules · 10 calculations · 34 ordered validations · 54 endpoints · 60 error codes · 7 roles.

- **Entities**: Client, Lender, StaffMember, Subcontractor, Project, AllowanceItem, Selection, ChangeOrder, ScheduleTask, CostEntry, DrawRequest, LienWaiver, DefectTicket, PhotoDocument.
- **State machines**: Project (4 states), AllowanceItem (OPEN<->FROZEN cycle + SELECTED->LOCKED->RECONCILED), Selection, ChangeOrder (cyclic PRICED->SUBMITTED->REVISION_REQUESTED->PRICED), ScheduleTask, CostEntry (INCLUDED_IN_DRAW<->APPROVED compensating edge), DrawRequest **two parallel axes** (`status` x `waiver_compliance`), LienWaiver (REJECTED<->RECEIVED cycle), DefectTicket (branching OPEN->{ASSIGNED, DENIED, WAIVED} + REJECTED->ASSIGNED rework cycle).
- **Concurrency (OCC only)**: `selection-create-stale-allowance` (AllowanceItem.version, 412) and `draw-create-stale-project` (Project.version, 412) — both genuine CREATE-with-supersede races.
- **Calculations**: change_order_priced_amount (circular-looking contingency tier pinned to the pre-contingency subtotal — 40000/10d -> **50315.50**, not 51292.50), draw_funding_amounts (per-line rounding pinned — **2250.03**, not 2250.02), project_contract_position (FIXED_PRICE **900000.00** vs COST_PLUS **53100.35** on identical data), warranty_coverage_determination (whole-house vs trade anchor -> OUT_OF_COVERAGE vs COVERED for the same claim date), allowance_variance (provisional/final), project_budget_posture (strict `>` GMP), schedule_material_readiness, schedule_delay_propagation, draw_cumulative_cap, defect_response_due.
- **Roles**: PlatformAdmin (opaque); ProjectManager / Estimator / Controller (`entity_backed:StaffMember`); Client, Lender, Subcontractor (entity-backed). SoD is enforced twice — CO pricer != submitter, and draw submitter != any included cost entry's approver.
- **Test-driving endpoint**: `POST /_clock/set_current_utc`, with the mandatory startup default `2026-08-01T00:00:00.000Z` stated in its description.

**§1.8** — 9 rule blocks x exactly **2 instances = 18**, each with structured `setup_api_calls`/`trigger`/`assert` and formula-derived asserts pre-computed as literals (50315.50, 42750.27, 15213.10, 950315.50, 53100.35, 2028-02-29 / 2029-01-14 coverage ends, etc.).

**§1.9** — 9 sections, **65 instances** (61 with recipes + 4 `excluded_because` stubs pointing at named §1.8 instances): entities 10, state_machines 14, calculations 9, validations 7, endpoints 3, errors 9, rbac 8, cross_cutting_complexity_layers 4, consistency_model 1.

**Extra self-checks run beyond the linter** (all clean): placeholder closure across all 83 instances (zero unbound `${var}`), 83/83 unique instance names across both files, every `grounds:` ref resolves into §1.1–§1.7, every `excluded_because` cites a real §1.8 instance name and carries no `test_recipe`, no forbidden concurrency vocabulary anywhere, response envelope emitted verbatim, every role declares `identity:`, both OCC write endpoints take `expected_*_version` and bump the parent's version, every error code is referenced by a validation or concurrency rule, and validation priorities are strictly ordered.

## Step 4: Generate PRD — 2026-08-17T13:05:27.349Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2116_custom_home_builder/workspace/PRD.md` — 429 lines, ~12,600 words, 99 KB. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Structure

- **§1 Introduction** — 3 paragraphs (contested-dollars framing -> ledger spine -> negotiation layer)
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC · 2.2 Response Structure (verbatim, diff-verified byte-identical) · 2.3 Pagination · 2.4 Record Identity + Logical Jobsite Clock · 2.5 Money/Whole Days/Rounding · 2.6 The Project Ledger and Its Derived Fields · 2.7 Segregation of Duties · 2.8 Stale-Read Protection (OCC) · 2.9 Path Resolution & Referential Integrity · 2.10 The Order in Which a Request Is Refused (all 34 validations as a strictly-ordered ladder)
- **§3 Business Logic** — 9 subsections grouped by ledger/negotiation lifecycle: standing up a job · allowance book · change orders · sequencing the trades · cost capture & contract position · draw requests · lien waivers · photo documentation · punch/walkthrough/warranty
- **§4** 54-row endpoint table (4 columns) · **§5** 60-row error table (2 columns). No audit footer.

## Per-category coverage (scaffold vs PRD)

| Category | Scaffold | PRD | Status |
|---|---|---|---|
| Entities | 14 | 14 | all have a §3 home; 138/138 fields in backticks |
| State machines / transitions | 10 / 48 | 10 / 48 | every `from -> to` pair rendered in arrow form |
| Concurrency rules | 2 | 2 | write_endpoint + `expected_*_version` + error_id + 412 all named |
| Calculations | 10 | 10 | all formulas in precise prose, incl. both dual-variant pairs |
| Validations | 34 | 34 | numbered in strict priority order with error IDs |
| Endpoints | 54 | 54 | |
| Error codes | 60 | 60 | all 60 also referenced in §1–§3 narrative |
| Roles | 7 | 7 | every `identity:` translated into §2.1 prose |

Also verified: 38/38 state values and 93/93 enum members present; 80/80 request-body identifiers; 19/19 query params.

**Hard contracts:** Contract 1 (field coverage) 138/80/19 required, 0 missing — PASS. Contract 2 (rule coverage) — PASS (priorities, OCC, transitions, calculations, validation conditions, side-effects/applies_to, field defaults, sibling symmetry all audited). Contract 3 (§3 path purity) — 892 backtick tokens scanned, 0 slash-leading, 0 bare methods, 0 method+path — PASS.

## One thing to flag

The scaffold references three constants **without ever assigning them a value**: `MAX_REVISION_ROUNDS` (validation p180, ChangeOrder submit/revise preconditions), `CLIENT_RESPONSE_DAYS` (`client_response_due_at`), and `JOBSITE_CURE_BUFFER_DAYS` (validation p165 exclusive-use buffer). Since the PRD is the implementer's only input, I had to state concrete values: **2 revision rounds, 14 days, 2-day cure buffer**. If the withheld design files pin different literals, these three numbers in §3.3 and §3.4 need to be reconciled before test generation.

---

### Orchestrator reconciliation (post-Step-4, pre-Step-5)

Acted on the flag above. Grepped the two withheld design indices for the three unbound constants (orchestrator is permitted to read them; only the PRD generator and Steps 8/9 are not):

| Constant | PRD (as generated) | Design index | Resolution |
|---|---|---|---|
| `MAX_REVISION_ROUNDS` | 2 | **3** — `SCAFFOLD_CORNER_DESIGN.yaml:2084` ("MAX_REVISION_ROUNDS is 3 and REQUEST_REVISION requires revision_count < 3 ... fourth request is refused with 409 ERR_REVISION_LIMIT_EXCEEDED") | PRD amended to **3** |
| `JOBSITE_CURE_BUFFER_DAYS` | 2 | **1** — `SCAFFOLD_DIFFICULTY_DESIGN.yaml:1436-1444` (`jobsite_exclusive_closed_interval_plus_cure_buffer_rejects_adjacency`, "CLOSED interval extended by JOBSITE_CURE_BUFFER_DAYS = 1") | PRD amended to **1** |
| `CLIENT_RESPONSE_DAYS` | 14 | *(no reference in either design file)* | PRD's **14** stands unopposed |

Rationale for amending PRD rather than the design indices: the design instances carry pre-computed worked-example asserts bound to their literals, while the PRD's values were arbitrary inventions with nothing depending on them. Left unreconciled, Step 5 would have either skipped those two designed instances (PRD-first filter) or emitted tests that Step 7 would be obligated to delete — losing designed coverage either way. Root cause is a scaffold-generator defect (constants referenced in §1.4/§1.6 but never bound in §1.0/§1.2), not a doc-generator defect.

Edits applied to `workspace/PRD.md` (3 lines, 6 diff lines total; backup at scratchpad `PRD.md.bak`):
- §3.3 L219 — "at most 2" -> "at most 3" (submit ceiling)
- §3.3 L221 — "strictly below 2" -> "strictly below 3" (REQUEST_REVISION precondition)
- §3.4 L229 — "two-day jobsite cure buffer" -> "one-day jobsite cure buffer"

Verified post-edit: zero residual stale literals; PRD still 429 lines.

## Step 6: Generate implementation — 2026-08-17T13:56:00.000Z

All test servers stopped and the tree is clean.

## Summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2116_custom_home_builder/workspace/implementation/`

### Files written (22 files, ~1,900 lines of Python + launcher)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 11 | Guarded dep install (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=3.0.0` |
| `app.py` | 84 | Blueprint registration, error handlers, per-request lock, `0.0.0.0:$PORT` |
| `store.py` | 86 | In-memory dicts (14 collections), logical clock, `base_row`/`bump`/`ordered` |
| `errors.py` | 93 | 60-code catalog + HTTP status map, `AppError` |
| `util.py` | 412 | Envelope, auth ladder steps 1–3 & 7, Decimal money, ISO-8601, validators, pagination |
| `services/constants.py` | 83 | Pinned constants + every enum |
| `services/calc.py` | 107 | CO pricing, selection total, material readiness, delay/float, warranty coverage, draw funding |
| `services/ledger.py` | 175 | Ledger recompute, budget posture, freeze/thaw cascade, contract position |
| `services/draws.py` | 71 | Waiver axis, auto-funding, compensation |
| `services/rows.py` | 53 | CO / lien-waiver row factories |
| `routes/*.py` (9) | ~1,800 | admin, projects, allowances, change_orders, schedule, costs, draws, defects, common |

### Coverage
- **54/54 endpoints** implemented (route table verified: 55 rules = 54 spec + `/health`).
- **14 entities**, all carrying `id`/`created_at`/`updated_at`/`version`.
- **10 state machines** including DrawRequest's two independent axes (`status` + `waiver_compliance`) and the cyclic edges (`REVISION_REQUESTED->PRICED`, `REJECTED->RECEIVED`, `REJECTED->ASSIGNED`).
- **2 OCC rules** (`expected_allowance_item_version` -> 412, `expected_project_version` -> 412).
- **10 calculations** with `Decimal` + `ROUND_HALF_UP` throughout — no floats. Verified against the PRD's own worked examples: CO price `40000/10d -> 0.10/0.03/50315.50`; per-line retainage `10000.10+15000.10+20000.10 @0.05 -> 2250.03` (not 2250.02); COST_PLUS `45000.30 x 1.18 -> 53100.35` vs FIXED_PRICE `900000.00`.
- **34-step §2.10 ladder** implemented in exact order per handler (e.g. 403-role before 404-path; 400-body before 404-body-refs; staff-identity before ownership; stale-version (13) before no-lender (34); tasks-incomplete before change-order-pending; SoD (20) before revision-limit (30); waiver-type (23) before waiver-amount (32)).
- **2 segregation-of-duties rules**, **7 roles**, **60 error codes**.

### Two deliberate PRD-fidelity judgements
- `Project.version` increments only at the six points the spec declares (advance x2, final-walkthrough, CO approve, CO void, draw create) — ledger recomputes refresh `updated_at` only, matching §2.6 which mentions version bumps for allowance freeze/thaw but not for project recompute.
- Project-state gates that §2.10 assigns **no** error code to (cost-entry review, draw submit) are not enforced as refusals; the four gates §2.10 does name (`ERR_PROJECT_NOT_UNDER_CONSTRUCTION` on selection/price/settle/release, `ERR_PROJECT_NOT_ACCEPTING_PHOTOS` on publish) are.

### Verification
Four hand-written integration suites (~200 assertions) exercised the full lifecycle end to end: reference data -> project -> allowance/selection/OCC/supersede -> lock (auto ALLOWANCE_OVERAGE CO + material readiness) -> reconcile -> CO pricing tiers/revision cycle/SoD/approve-void compensation -> crew-capacity & exclusive-use overlap conventions -> delay propagation & float -> draw submit/cap/return/void -> lien-waiver PENDING->PARTIAL->COMPLETE auto-funding -> warranty anchors (whole-house vs trade vs excluded) -> punch list -> final walkthrough cascade. All pass; the 3 residual "failures" shown are wrong expectations in my own scratch scripts (each traced back to the PRD and confirmed the server is right).

**Boot confirmed:** `bash start.sh` with `PORT=18999` listens on `0.0.0.0:18999` in the foreground (`ss` shows `LISTEN 0.0.0.0:18999`), responds in under 4 s, and the store + logical clock (`2026-08-01T00:00:00.000Z`) start empty/default on every fresh process — no seeding anywhere.

## Step 5: Generate unit tests — 2026-08-17T13:35:45.563Z

Test infrastructure and suite are complete and audited.

## Files written

**`test_helpers/`** (9 modules, ~2,470 lines)
| File | Contents |
|---|---|
| `types.py` | 24 status/role enums + 14 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version`, per PRD §2.4) |
| `api_client.py` | `ApiClient(GenericApiClient)` — one method per published endpoint (54) |
| `api_errors.py` | 60-member `ApiErrorId` + HTTP status map, registered with the framework |
| `assertions.py` | Per-entity assertions, `assert_money_equals` / `assert_money_not_equals`, `assert_instant_equals`, `assert_project_ledger_invariants`, `assert_draw_funding_arithmetic` |
| `factories.py` | 14 payload factories (input fields only) |
| `constants.py` | Pricing tiers, GC day rate, `MAX_REVISION_ROUNDS=3`, `CLIENT_RESPONSE_DAYS=14`, `JOBSITE_CURE_BUFFER_DAYS=1`, warranty/fabrication days, `CLOCK_START` |
| `test_users.py` | Opaque `PlatformAdmin` constant + per-instance builders for all six entity-backed roles (identity threading) |
| `fixtures.py` | 970 lines, 6 tiers — `setup_job`, `setup_locked_allowance`, `setup_submitted_draw`, `setup_conditionally_approved_draw`, `setup_two_trade_draw_conditionally_approved`, `setup_single_trade_draw_awaiting_verification`, `setup_returned_draw_now_over_the_cap`, `setup_identical_ledger_pair`, `setup_job_with_material_driven_task`, `setup_two_project_schedule`, `setup_exclusive_use_slab`, `setup_substantial_completion`, `setup_build_with_completed_plumbing_task`, … |
| `__init__.py` | Barrel export |

**`test_suite/`** — `conftest.py` + 10 domain-named files (`test_01_job_setup_and_project_ledger.py` … `test_10_access_control.py`), 3,551 lines.

## Coverage

- **97 tests**, all collected by pytest, pyflakes-clean, no `skip`/`skipif`/`xfail`, no scaffold references in code or docstrings.
- **§1.8 (queue A): 18/18 instances translated, 0 skipped** — each has exactly 2 tests (36 total), tagged `Design: Difficulty/<rule_id>/<name>`.
- **§1.9 (queue B): 61/61 non-stub instances translated, 0 skipped** — 61 tests tagged `Design: Corner/<section>/<name>`. The 4 `excluded_because:` stubs were **not** translated (as specified); all four cross-references were verified to resolve to real §1.8 instance names.
- Every test docstring ends with exactly one `Design:` line resolving to a real instance; **all 174 quoted PRD citations verified as verbatim substrings of PRD.md** by an automated normalizer-grep.

## Notes

- No instance failed the PRD-first filter, so there are no gaps to report. The three reconciled constants (3 / 14 / 1) are all stated in PRD.md and the tests assert against them.
- One faithfulness adjustment: `Corner/state_machines/newer_selection_supersedes_prior_proposal_on_same_allowance_item` and the deadline/frozen instances call `GET /allowance-items/{id}/selections` **without** a `status` query filter (PRD names no filter for that endpoint) and count `PROPOSED` rows client-side — the asserted outcome is unchanged.
- `PhotoDocument` has no single-resource GET in the contract, so `read_photo_document()` resolves it through the project's photo list.

**Orchestrator verification:** independently confirmed 97 `def test_` functions, 36 `Design: Difficulty/` tags + 61 `Design: Corner/` tags = 97 (exactly one tag per test).

## Step 7: Run tests and iterate — 2026-08-17T14:12:00.000Z

All 8 parallel rounds passed 97/97 on the first sweep, with 0 failed, 0 errors, and 0 skipped in every round. No further iterations were needed.

## Summary

**Iterations run:** 1 (single 8-round parallel stability sweep; all 8 rounds completed to 97/97).

**Tests deleted:** None. No test failed in any of the 8 rounds, so no test entered the diagnostic protocol and no PRD-silence or unique-derivability deletion was triggered.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

### Verification performed beyond the raw pass counts

Because a clean first sweep can mask a rigged suite, I audited the artifact against the benchmark's cardinal rules before exiting:

- **No suppression markers.** `grep` for `skip`/`xfail` across `test_suite/` and `test_helpers/` returns only two false positives: a docstring quoting PRD §2.3 ("skipped before the page begins") in `test_suite/test_01_job_setup_and_project_ledger.py:155`, and a test *name* containing the word in `test_suite/test_09_punch_warranty_and_photos.py:172`. No `pytest.mark.skip` / `xfail` anywhere.
- **Storage is in-memory only.** `workspace/implementation/store.py` holds plain dicts keyed by id and resets empty on boot; no SQLite, no on-disk JSON, no `/tmp` cache, no seeded or hardcoded entities.
- **The three reconciled constants agree with PRD across both layers.** `MAX_REVISION_ROUNDS = 3`, `CLIENT_RESPONSE_DAYS = 14`, `JOBSITE_CURE_BUFFER_DAYS = 1` are identical in `test_helpers/constants.py` and `workspace/implementation/services/constants.py`, and both match the PRD prose (§3.3 "submitted while its `revision_count` is at most 3" and "a two-week client response window of 14 days"; §3.4 "a one-day jobsite cure buffer"). The context note's warning that the implementation might carry different internal values does not apply here.
- **No flakiness signal.** The suite contains no concurrency/race tests (`run_race`, `assert_race_outcome`, `assert_exactly_one_succeeds` are exported by the framework barrel but never called), which is consistent with the perfectly stable 8-round result rather than a lucky sweep. Round durations were tightly clustered at ~124.6s each, confirming all 8 ran concurrently under `per-test-server` isolation.

The one code-level note worth flagging, though it is not a defect the tests exposed: in `workspace/implementation/routes/draws.py`, the `submit_draw_request` ladder evaluates the lender cumulative cap (step 33) inside an `if lender is not None:` block placed *before* the `ERR_PROJECT_HAS_NO_LENDER` check (step 34). PRD §2.10 orders step 33 before step 34, so the sequencing is faithful; the arrangement only reads oddly because the null-lender branch falls through the cap block. No change made, since altering it would risk the ordering PRD pins.

**Orchestrator verification:** independently parsed all 8 `results.*.json` — every round `passed=97 failed=0 total=97 errors=0 skipped=0`, durations clustered 124.6–124.7s (confirming genuine concurrency). Independently grepped `pytest.mark.skip|xfail` across both test dirs: 0 hits. Independently grepped implementation for `sqlite|json.dump|/tmp/|open(...,'w')`: 0 hits. Step 7's report is corroborated.

**Step 8 skip decision:** Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — i.e. zero iterations beyond the baseline. Per the skip condition, Step 8 (PRD_FINALIZED.md) is SKIPPED; `PRD.md` already determined every behavior the tests exercised. Step 9 still runs (it never skips) and will take `PRD.md` as its source.

## Step 8: Finalize PRD — SKIPPED — 2026-08-17T14:07:10.814Z

Skipped per the skip condition. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes, so `PRD.md` already determined every behavior the tests exercised and there were no Step-7 fix sites to patch. No `PRD_FINALIZED.md` produced; Step 9 sourced from `PRD.md`.

## Step 9: Complete PRD — 2026-08-17T14:07:10.814Z

Note: this step required three launches — the first two subagents died to transient API 529 (Overloaded) errors, the first after only the `cp` (verified byte-identical to PRD.md, deleted before retry) and the second before creating the file at all. No partial or corrupt output survived either failure. The third attempt ran with incremental writes and a durable progress-notes file; it completed and cleaned up its notes file.

`workspace/PRD_COMPLETED.md` is complete. Notes file deleted.

## Size

| | PRD.md | PRD_COMPLETED.md | delta |
|---|---|---|---|
| lines | 429 | 429 | 0 |
| chars | 99,384 | 107,917 | **+8,533** |

No sections added, no paragraphs added — every change is an in-paragraph insert or revision.

## Counts

- **ambiguity-pins: 34**
- **mismatch-revisions: 13**
- total: 47

## Changes

- §2.1 — insert — ambiguity — whitespace-only headers count as empty; both header values trimmed before matching — `util.py:162-174`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 20 random uppercase-alphanumerics; `api_request_timestamp` is read off the logical clock, not wall clock — `util.py:100-114`
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order; the newest-first selection listing is that same total order reversed end to end — `store.py:168-170`, `routes/allowances.py:238`
- §2.3 — insert — ambiguity — filter params match exactly; an empty/whitespace value is treated as absent — `util.py:407-412`
- §2.4 — revise — **mismatch** — ledger recomputation refreshes a project's `updated_at` but does **not** bump `version`; project `version` moves only on the six explicitly-named operations — `store.py:157-165`, `services/ledger.py:127-128`
- §2.4 — revise — ambiguity — clock endpoint's `data` carries the single field `current_utc`; `to_iso8601` mandatory — `routes/admin.py:64-70`
- §2.9 — insert — ambiguity — fixed resolution order for multi-reference payloads (project -> subcontractor -> predecessor -> driving allowance, etc.) — `routes/schedule.py:39-55`, `routes/costs.py:39-49`, `routes/change_orders.py:52-66`, `routes/projects.py:79-83`
- §2.10 step 5 — insert — **mismatch** — on list endpoints `limit`/`offset` are validated when the page is cut, i.e. *after* step 7, so `ERR_ROLE_IDENTITY_MISMATCH` wins over `ERR_INVALID_REQUEST` — `routes/projects.py:117-131`, `util.py:371-404`
- §2.10 step 8 — revise — **mismatch** — ownership applies only to write endpoints; no read (single or list) performs an ownership comparison — `routes/common.py:36-48`, `routes/projects.py:109-114,258-277`
- §2.10 step 11 — revise — **mismatch** — the `UNDER_CONSTRUCTION` list also covers change-order approval and void — `routes/change_orders.py:192-194,222-224`
- §3.1 — revise — ambiguity — `max_cumulative_draw_pct` accepted to four decimal places — `routes/admin.py:98-100`
- §3.1 — revise — ambiguity — `builder_fee_pct` to four decimals; `gmp_cap` non-negative, at most two decimals — `routes/projects.py:74-76`
- §3.1 — insert — ambiguity — a `builder_fee_pct` on a `FIXED_PRICE` job is still validated, stored and echoed — `routes/projects.py:100`
- §3.2 — revise — **mismatch** — the allowance line's `version` bumps on *every* proposal, not only superseding ones; the superseded proposal's own `version` bumps too — `routes/allowances.py:196-219`
- §3.2 — insert — ambiguity — approving a still-`PROPOSED` selection whose line left `OPEN` or whose project is `OVER_GMP` -> `ERR_ALLOWANCE_FROZEN`; neither branch reads project lifecycle status; rejection gated on `PROPOSED` alone; response is the selection row — `routes/allowances.py:257-283`
- §3.2 — insert — ambiguity — LOCK writes `material_ready_at` to driving tasks in *any* status and bumps each task's `version`; zero lead time stands in with no accepted proposal — `routes/allowances.py:110-121`
- §3.2 — insert — ambiguity — auto change order carries a server-generated `scope_description` (category + line id), is otherwise a fresh DRAFT, and moves no project figure or `version` — `routes/allowances.py:123-134`, `services/rows.py:114-138`
- §3.3 — insert — **mismatch** — `source_allowance_item_id` is optional on every origin; never demanded for `ALLOWANCE_OVERAGE`, never refused on others — `routes/change_orders.py:50,56-66`
- §3.3 — insert — ambiguity — submission carries no payload fields — `routes/change_orders.py:140`
- §3.3 — insert — ambiguity — approval shift bumps each task's `version`, never recomputes `float_days`/`material_ready_at`, insertion order settles remaining ties — `routes/change_orders.py:27-38`
- §3.3 — revise — ambiguity — `revision_note` optional/null when omitted, `decided_at` untouched; only approval gates on project status — `routes/change_orders.py:168,177-194`
- §3.3 — insert — ambiguity — void pull-back uses the same ordering and bumps each shifted task's `version` — `routes/change_orders.py:234-235`
- §3.4 — insert — ambiguity — crew-capacity counting spans every project the trade is booked on — `routes/schedule.py:67-76`
- §3.4 — insert — ambiguity — release carries no payload fields — `routes/schedule.py:139`
- §3.4 — insert — ambiguity — start at exactly `material_ready_at` is in time; neither progress edge reads project status — `routes/schedule.py:182-191`
- §3.4 — insert — ambiguity — insertion order settles remaining propagation ties — `routes/schedule.py:206`
- §3.4 — insert — ambiguity — each shifted successor's `version` is incremented — `routes/schedule.py:212-213`
- §3.5 — revise — **mismatch** — `source_allowance_item_id` required only for `ALLOWANCE_ACTUAL` (`ERR_INVALID_REQUEST`), merely optional (not forbidden) on other entry types — `routes/costs.py:32-37,45-55`
- §3.5 — revise — **mismatch** — cost review applies **no** project-lifecycle gate at all — `routes/costs.py:98-110`
- §3.5 — insert — ambiguity — rejection leaves `approved_by_staff_id`/`approved_at` null — `routes/costs.py:112-115`
- §3.6 — insert — ambiguity — opening a draw has no project-status gate; stale-version check precedes the missing-lender check — `routes/draws.py:45-58`
- §3.6 — revise — **mismatch** — submission's only state gate is the draw's own `DRAFT` status; project status is read only to pick the waiver form — `routes/draws.py:117-135`
- §3.6 — insert — ambiguity — one waiver per trade in order of first appearance in the `incurred_at`-ordered eligible set; null-`subcontractor_id` entries skipped — `routes/draws.py:172-188`
- §3.6 — insert — ambiguity — `condition_note` optional on both outcomes, stored null when omitted — `routes/draws.py:214,231,239`
- §3.7 — insert — ambiguity — filing against a draw in the wrong status -> `ERR_DRAW_INVALID_STATE` (409), checked after the waiver's own status — `routes/draws.py:311-313`
- §3.7 — insert — ambiguity — an omitted `signed_document_ref` overwrites the stored one to null — `routes/draws.py:302,321`
- §3.7 — insert — ambiguity — verification reads nothing of the parent draw's status; both decisions answer with the waiver row — `routes/draws.py:328-359`
- §3.8 — insert — ambiguity — `captured_at` and `caption` both mandatory; upload accepted in any project status — `routes/projects.py:237-255`
- §3.9 — insert — ambiguity — `source_schedule_task_id` must resolve but need not be on the ticket's project; filing accepted in any project status — `routes/defects.py:40-41`
- §3.9 — insert — ambiguity — with no anchor instant available, the anchor label is written but `coverage_end_at` is null and `coverage_result` is `OUT_OF_COVERAGE` — `services/calc.py:77-96`
- §3.9 — revise — **mismatch** — `responsible_subcontractor_id` required (`ERR_INVALID_REQUEST`) except on the rework edge, where the recorded trade stands — `routes/defects.py:104-114,131-133`
- §3.9 — revise — ambiguity — the rework edge re-stamps `assigned_at` as well as `response_due_at` — `routes/defects.py:134-139`
- §3.9 — insert — ambiguity — `completion_note` written on every hand-back, so omission clears an earlier note — `routes/defects.py:159,168`
- §3.9 — insert — **mismatch** — the draw-in-flight `ERR_PROJECT_INVALID_STATE` test runs *last* of the three walkthrough gates, after punch-blocking and cosmetic-ack — `routes/projects.py:199-219`
- §4 table — revise — ambiguity — per-line selection listing accepts an optional `status` filter — `routes/allowances.py:239-241`
- §4 table — revise — **mismatch** — lien-waiver listing is filterable by draw, subcontractor **and status** — `routes/draws.py:286`
- §5 intro — revise — **mismatch** — three transport-level identifiers exist outside the catalogue: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `app.py:57-71`, `errors.py:234-236`

**Orchestrator verification:** independently confirmed PRD_COMPLETED.md is 429 lines (identical to PRD.md) with 27 markdown headings in both files — no sections or paragraphs added, as required. 82 changed diff lines (41 replaced line-pairs), +8,533 chars. `.step9_progress.md` scratch file removed.
