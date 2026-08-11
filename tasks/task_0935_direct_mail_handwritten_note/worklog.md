# Worklog — task_0935_direct_mail_handwritten_note

Scenario (verbatim): 935. Direct-Mail & Handwritten-Note Fulfillment: campaign & template/handwriting-style, mailing-list import & CASS/dedupe, print/robot-write & envelope, postage & bulk (EDDM) rate, scheduling & drip, address-verification & return-handling, proof & approval, reporting

Difficulty target: **beyond-Expert** (user: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-08T17:16:00.000Z

Created `tasks/task_0935_direct_mail_handwritten_note/` and `workspace/`. Index 0935 chosen as max(existing task_NNNN) + 1 (0934 was highest).

## Step 3: Copy INSTRUCTION.md — 2026-08-08T17:16:30.000Z

`cp ./INSTRUCTION.md tasks/task_0935_direct_mail_handwritten_note/workspace/INSTRUCTION.md` (done early, out of order — no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-08T18:27:00.000Z

All three artifacts are generated and clean.

## Counts

| Dimension | Value |
|---|---|
| Entities | **18** |
| Endpoints | **78** (incl. 1 `/_clock` test-driving endpoint) |
| State-machine axes | **15** across 11 entities — **13 non-linear**. Campaign carries **3 parallel axes** (lifecycle/compliance/billing); ListRecord carries **4 parallel axes** (cass/dedupe/mail/move). Cycles: Campaign ACTIVE↔PAUSED, Campaign CLEAR↔HOLD, MailingList CASS_RUN↔DEDUPED self-loops, ListRecord dedupe reset, ListRecord RETURNED→QUEUED, ListRecord cass recovery, Proof REJECTED→SUBMITTED, ProductionRun RUNNING↔FAILED, InkLot OPEN↔QUARANTINED + DEPLETED→OPEN, DripStep SCHEDULED↔PENDING, MailJob two revert edges to DRAFT; branching: ListRecord CASS 2-way and dedupe 4-way, move 2-way, Proof approve/reject, ReprintRequest fulfil/deny |
| Calculations | **13**, of which **7 are dual-variant** (`dedupe_screen` EXACT/HOUSEHOLD, `postage_estimate` PROVISIONAL/FINAL, `eddm_route_pricing` SATURATION/HDPLUS, `production_capacity_plan` SINGLE_PASS/SPLIT_RUN, `mail_date_derivation` ANCHOR_IN_HOME/ANCHOR_MAIL_DATE, `return_settlement` REPRINT/REFUND, `campaign_postage_reconciliation` LEDGER_REPLAY/COUNTER_SNAPSHOT) |
| Error codes | **43** |
| Ladder rungs | **41**, priorities 1..41, all distinct |
| OCC rules | **4** (MailJob, Template, ListRecord, DripSchedule parents) |
| Conservation invariants | **4** (postage money, ink volume, machine slot-minutes, piece-count partition) |
| Max cascade depth | **5** (CASCADE A: template edit → version_no → proof SUPERSEDED → job COMMITTED→DRAFT → run VOIDED → ink/slot release + postage REFUND); CASCADE B depth 4, CASCADE C depth 4 |
| Constants declared | 60 in `global_constants` + per-calculation blocks, all with units and inclusive/exclusive boundaries |
| Design instances | §1.8 = **25** (9 rules × 2–3), §1.9 = **53** (49 with recipes, 4 `excluded_because` stubs) |

## Seam coverage (check E)

1. **Two mail paths, one pipeline** — `MailJob.job_kind` ADDRESSED/EDDM + `EddmRouteSelection`; rung 13 `ERR_EDDM_NOT_APPLICABLE` (run reservations/returns/NCOA/reprints on EDDM) vs rung 14 `ERR_JOB_KIND_MISMATCH`; EDDM-only SM edge COMMITTED→MAILED skips IN_PRODUCTION entirely.
2. **CASS/DPV → tier → rate fork** — `cass_deliverability_tier`, `ListRecord.deliverability_tier`, `postage_estimate`'s AUTOMATION/RETAIL/UNMAILABLE split.
3. **Non-monotone dedupe→presort→rate chain** — `dedupe_screen` × `presort_tier_selection`: HOUSEHOLD collapse takes 6 automation pieces to 5, dropping PRESORT_MIXED_AADC (31.8¢) to NO_PRESORT (51.0¢), so **243¢ provisional becomes 307¢ final on fewer pieces**.
4. **Handwriting style + robot-pen as consumable** — `HandwritingStyle.ink_type`/`chars_per_minute`, `WritingMachine.daily_capacity_minutes`, `InkLot.remaining_ul`, `production_capacity_plan`, rungs 32/39/40.
5. **Postage escrow money conservation** — `PostageLedgerEntry` (TOPUP/DRAW/REFUND/FORFEIT), `Account.permit_balance_cents`, `commit_settlement`, class-dependent `RETURN_FEE_CENTS_*` (0 First-Class, 89 Marketing).
6. **Proof approval expiry + supersession** — `Proof.pinned_template_version`/`expires_at`; rung 24 `ERR_PROOF_NOT_APPROVED` vs rung 25 `ERR_PROOF_APPROVAL_STALE` are separately reachable.
7. **Drip with in-home targeting + blackouts** — `mail_date_derivation`; rungs 27/28/29 give three distinguishable temporal errors (past request vs unresolvable blackout vs unreachable derived date).
8. **NCOA + return handling with capped reprint** — `ListRecord.move_status`, `ReturnEvent.entitlement`, `ReprintRequest`, rungs 37/38.
9. **Ledger-replay reporting** — `GET /mail/campaigns/{id}/postage-reconciliation` must include FORFEIT rows (395¢ vs the 306¢ counter shortcut); `deliverability-report` enforces the 4-bucket partition.
10. **Global write gate** — `Campaign.write_gate` derived from compliance/billing; rungs 9 and 10 sit above every per-endpoint state gate, with compliance-releases the sole rung-9 exemption and no rung-10 exemption.

## Self-check results

- **B (YAML lint)** — all three `yaml.safe_load` clean. Two known offenders were found and fixed: trailing `?` in `input:` flow lists, and nested `[` in `grounds:` flow lists.
- **C (no undeclared constants)** — 122 ALL_CAPS tokens scanned, **0 undeclared**; every threshold/window/cap/rate has a value plus stated unit and inclusivity.
- **D (reachability)** — 15 axes, **0** orphan/dangling enum states, **0** unreachable `from:` states; 17 arithmetic-feasibility checks all pass. Two genuine unreachability defects were found and fixed in-flight: rung 24 (`ERR_PROOF_NOT_APPROVED`) was pre-empted by the schedule state gate (fixed by admitting DRAFT at rung 17 plus a DRAFT→SCHEDULED edge), and rung 13 (`ERR_EDDM_NOT_APPLICABLE`) had no reachable trigger (re-scoped to robot-pen runs on EDDM jobs, plus the EDDM COMMITTED→MAILED edge).
- **F (total order)** — 41 rungs, 41 distinct contiguous priorities; **all 43 error codes** are produced by at least one rung, and **all 43** are asserted by at least one design instance. 78 instance names, no duplicates; no dangling `excluded_because` targets. No forbidden concurrency vocabulary anywhere.
- **`scaffold_lint.py`** (1049 calls scanned): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Files

- `SCAFFOLD.yaml` — 3534 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2522 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2770 lines

One note for the downstream PRD/test steps: the arithmetic backbone is pinned to a 7-record fixture (6 `Y` + 1 `D`, with a Smith household pair) — provisional 243¢, final 307¢ after HOUSEHOLD collapse, settlement 275/29/553, and the round-per-tier-then-sum trap that yields 243 rather than 242. Presort thresholds were deliberately scaled down (12/9/6 pieces) so every tier boundary is reachable through API-driven fixtures.

**Orchestrator independent verification:** all three files `yaml.safe_load` clean; `SCAFFOLD.yaml` carries neither design key; `endpoints[]` length = 78.

## Step 4: Generate PRD — 2026-08-08T19:05:00.000Z

`workspace/PRD.md` — **560 lines, 16,938 words, 115,802 characters**. Structure: §1 Introduction (3 paragraphs), §2 with 11 subsections (2.1 roles/scope, 2.2 verbatim envelope, 2.3 pagination, 2.4 identity/versioning/logical clock, 2.5 campaign write gate, 2.6 the 41-rung ladder, 2.7 OCC, 2.8 money/rounding/ledger, 2.9 the two mail paths, 2.10 conservation invariants, 2.11 path resolution), §3 with 9 lifecycle-ordered subsections, §4 endpoint table, §5 error table. No audit footer.

### §2 Self-audit coverage counts

| Scaffold category | Required | Discoverable in PRD | Missing |
|---|---|---|---|
| `entities[].fields[].name` | 124 | 124 | 0 |
| `endpoints[].input` identifiers | 78 | 78 | 0 |
| Path parameters | 16 | 16 | 0 |
| Report-shape output fields (`draw_cents`, `record_total`, `current_utc`, …) | 14 | 14 | 0 |
| Error codes in §2/§3 **prose** (not only the §5 table) | 43 | 43 | 0 |
| Ladder rungs referenced by number in prose | 41 | 41 | 0 |
| State transitions, all 15 axes (70 entries; 69 unique — `MailJob COMMITTED → DRAFT` appears twice, once via void and once via CASCADE A) | 69 unique | 69, each with explicit `FROM → TO` arrow notation | 0 |
| Calculations (13, of which 7 dual-variant) | 13 | 13, both variants of each of the 7 forks rendered with equal density | 0 |
| OCC rules | 4 | 4 (endpoint + `expected_*_version` + parent + `ERR_STALE_VERSION` + 412) | 0 |
| Conservation invariants | 4 | 4 (§2.10) | 0 |
| Declared global constants with a literal value | 47 | 45 literal + 2 (`HANDLING_PCT`, `VOLUME_CREDIT_PCT`) rendered as "eight percent"/"five percent" per the no-pseudocode rule | 0 |
| Cascades | A (7 hops), B (4 hops), C (4 hops) | all hops enumerated | 0 |

Hard contracts: **Contract 1 PASS** (0 missing names), **Contract 2 PASS**, **Contract 3 PASS** (1,018 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path).

### Un-adjudicated friction points (both readings rendered neutrally, none resolved)

1. **§2.10** — Whether the per-list counters `unmailable_count`/`duplicate_count` inherit the report's unmailable-first precedence (partition holds unconditionally) or are literal independent counts (a record that is both unmailable and a duplicate is counted twice).
2. **§3.5** — Approval's stated precondition that `pinned_template_version` still equals `Template.version_no` has no rung scoped to approval (rung 25 guards schedule/commit). Reading A: answer `ERR_PROOF_APPROVAL_STALE`. Reading B: `expected_template_version` is the only template guard approval needs, and it proceeds.
3. **§3.5** — Whether the proof *collection* read materialises `APPROVED → EXPIRED` on each expired row, or only the single-proof read and gate evaluations do.
4. **§3.6** — Scheduling with no `target_in_home_date` in the body **and** none on the job. Reading A: `ERR_VALIDATION` for a missing anchor. Reading B: the body value is an override, and a null anchor falls to whichever temporal rung it first offends.
5. **§3.6** — Whether a `PENDING` sibling step holding no `computed_mail_date` participates in the rung-30 minimum-gap comparison.
6. **§3.8** — Whether a first-ever draw against a `SEALED` lot landing exactly on the 500 µL reserve carries it `SEALED → OPEN → DEPLETED` in one reservation, or leaves it at `OPEN` (depletion being declared only as an edge out of `OPEN`).
7. **§3.8** — Which rung reports "not every production run has finished" when dropping an addressed job: `ERR_MAIL_JOB_INVALID_STATE` (rung 17) or `ERR_RUN_INVALID_STATE` (rung 19). No rung is scoped to it.
8. **§3.9** — Whether a `FORFEIT` that would drive `permit_balance_cents` below zero is allowed through (rung 41 is scoped to commit only) or refused to keep the escrow non-negative.
9. **§3.9** — Whether `reprint_count` is a per-campaign figure evaluated against the cited `campaign_id` (a record mailed in two campaigns may be reprinted once in each) or a single running counter on the record.

### Reconciliations made

- **`Campaign.mailed_piece_count`** — field definition (sum of `billable_piece_count` over jobs in `MAILED`/`CLOSED`) vs the `QUEUED → MAILED` side-effect wording ("increments"). Field definition made authoritative in §3.8; every narrative mention phrased as "the sum being refreshed" so §3.8 and §3.9 hop 2 cannot drift.
- **§2.10 partition bullet** — originally asserted unconditionally that the four bucket counts sum to `record_count`, contradicting the friction paragraph two lines below. Reworded to attribute exclusivity and the sum to the campaign-level report, leaving the list-counter question to friction point 1.
- **Rung 15 vs rung 9** — §2.6's third structural consequence vs §3.4's "rung 15 demands `compliance_status` CLEAR"; §3.4 now notes rung 15 is only ever heard on a campaign whose gate is `OPEN`.
- **`ProductionRun FAILED → RUNNING`** — scaffold edge omits the write-gate precondition its `RESERVED → RUNNING` sibling carries. Since rungs 9/10 are unconditional over every write resolving to a campaign, §3.8 states the gate applies to starts from either state.

Did not open either design index or any other `task_*/` directory.

## Step 5: Generate unit tests — 2026-08-08T19:22:00.000Z

Test infrastructure and suite are complete and audited.

### Files written

**`test_helpers/`** (2,505 lines) — `__init__.py` 40, `api_client.py` 321 (one method per PRD endpoint), `api_errors.py` 100 (43 error ids + HTTP map), `assertions.py` 358 (incl. `assert_same_instant` / `parse_instant`), `constants.py` 104, `factories.py` 254, `fixtures.py` 740 (`build_addressed_scenario`, `build_eddm_scenario`, `build_drip_scenario`, `build_returned_record_scenario`, `build_mailing_list`, 30+ primitives), `test_users.py` 65, `types.py` 523.

**`test_suite/`** (2,980 lines) — `conftest.py` (42) plus 10 test files: `test_01` 15, `test_02` 9, `test_03` 5, `test_04` 10, `test_05` 9, `test_06` 11, `test_07` 10, `test_08` 17, `test_09` 9, `test_10` 4.

### Tests emitted — 99 total (queue A 50 / queue B 49)

- All **25** difficulty instances carry exactly 2 tests each.
- All **49** non-stub corner instances carry ≥1 test.
- All **4** `excluded_because` stubs verified to resolve to real difficulty instances; none translated.
- **0** untagged, **0** dual-tagged, **0** unresolved tags. No `skip`/`skipif`/`xfail` anywhere.

### Instances SKIPPED

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter.

Three *individual assertions* from scaffold recipes were dropped as non-uniquely-derivable (the instances themselves still got their tests):
1. `template_edit_cascade_depth_five` — dropped `drawn_postage_cents == 0`, `refunded_postage_cents == 306`, `pinned_template_version == null`, `ListRecord.mail_status == NOT_MAILED`. §3.2 hop 3 scopes field-clearing to jobs reverting *from PROOFED/SCHEDULED*; it never says what a COMMITTED revert clears, and hop 6 mentions only the REFUND row and the balance. Kept the six hops PRD does state.
2. `list_record_four_parallel_axes` and `second_reprint_fulfilment` — dropped `return_fee_cents == 0` on a **REPRINT**-entitled return. §3.9 fixes the fee only under the REFUND branch; a reader could faithfully store 89 there without charging it. The REFUND-branch `== 89` is asserted.
3. `campaign_pause_unschedules_scheduled_drip_steps` — dropped `shifted_days == 0`; "clearing … `shifted_days`" does not say whether that means 0 or null.

### Agreement-by-construction arithmetic (all nine frictions avoided)

- **F1 (per-list `unmailable_count`/`duplicate_count`)** — no roster ever makes one record both UNMAILABLE-tier *and* a duplicate. The only non-mailable record is Gus Vale (DPV `N`), whose `household_key` = `vale|900 ivy pl|60609` and `exact_key` = `gus|vale|900 ivy pl|60609` are shared with no other row, so he is the first member of his own group under both modes (`HOUSEHOLD_HEAD` / `UNIQUE`), never `DUP_*`. The 8-record list reads **automation 5, retail 1, unmailable 1, duplicate 1, sum 8** under precedence-first *and* under literal independent counting. The 7-record roster has zero UNMAILABLE rows; the all-`N` roster in test_04 gets no dedupe run at all.
- **F2 (approval with `pinned_template_version ≠ version_no`)** — the one test with that mismatch (pinned 1, `version_no` 2) also carries `expected_template_version = 1` against a live Template `version` of 2. Rung 11 sits above rung 25, so *both* readings return `ERR_STALE_VERSION` (412).
- **F5 (date-less PENDING sibling in the rung-30 gap check)** — in every drip test the sole sibling is `PENDING` *with* `computed_mail_date = 2026-06-05` (asserted before the next step is added), so both readings examine the same set. Gaps: 06-05 vs 06-06 = 1 day → refused; 06-05 vs 06-07 = 2 days → accepted.
- **F6 (draw landing exactly on the 500 µL reserve)** — the thin lot is **501 µL** and the single-piece draw is `ceil(400 × 4.0 / 1000) = 2` µL; 501 − 2 = **499 < 500**, a strict shortfall refused at rung 40, never landing on 500. No test asserts `DEPLETED`.
- F3: `list_proofs` is never called. F4: AST-verified that all 11 direct `schedule_mail_job` calls pass `target_in_home_date` in the body. F7: every addressed mail-drop follows a `COMPLETED` run. F8: balance is ≥499,694 before any 89-cent forfeit. F9: the reprint cap test uses a single campaign.

### Audit counts

**E — response-field discipline.** 124 distinct subscripted/`.get()` names; **119 are response/payload field names and all 119 appear verbatim in PRD.md**. The 5 non-matches are keys of the local `TEST_USERS` header dictionary, not API fields.

**F — numeric literal discipline.** **205 numeric literals inside `assert` statements, 38 distinct values**, each hand-derived: rate-card products (`6×31.8=190.8→191`, `1×51.6→52`, sum **243**; `5×51.0=255`+52=**307**; `6×58.0=348`+73=**421**; `12×22.3=267.6→268`; `12×25.6=307.2→307`; `5×22.3=111.5→112`); settlement (`250+ceil(0.08×307)=275`, `307+275=582`, `floor(0.05×582)=29`, `582−29=`**553**; `250+ceil(0.08×51)=255`, `51+255=`**306**; `250+ceil(0.08×112)=259`, `112+259=`**371**); capacity plan (`ceil(400/4000)=1`, `1+12×1=13`, `1+12×2=25`, `ceil(400×4.0/1000)=2`, `ceil(1200×4.0/1000)=5`); conservation (`20000−2=19998`, `20000−5−5=19990`, `500000−553=499447`, `500000−306=499694`, `−89=499605`, `500000−371=499629`); `89` (§3.9 marketing return fee); `75.0` = `100×6/8`; `242` is PRD's own named wrong answer.

**G — ordering discipline.** **9 list-index subscripts inside asserts, none depending on a server ordering rule.** `steps[7]` indexes a Python list built from eight successive 201 responses; `draws[0]`, `forfeits[0]`, `refunds[0]` each follow an `assert len(...) == 1`. The only server-ordered collection read (`GET /mail/list-records` with `limit=2`) asserts page size and `meta` only.

## Step 6: Generate implementation — 2026-08-08T19:22:00.000Z

Implementation complete and verified. `workspace/implementation/` — 22 files, **3,782 lines** of Python + `start.sh` + `requirements.txt`.

| module | lines | role |
|---|---|---|
| `ladder.py` | 326 | the 41-rung ordered pipeline + gate resolvers |
| `routes/jobs.py` | 418 | mail jobs, estimate/schedule/commit/void/mail, EDDM routes |
| `routes/lists.py` | 299 | mailing lists, CASS, dedupe, lock, records, NCOA, returns |
| `serial.py` | 294 | 18 serializers |
| `routes/production.py` | 245 | robot-pen runs |
| `calc.py` | 236 | the 13 calculations |
| `routes/admin.py` | 220 | clock, accounts, escrow, blackouts, styles, machines, lots |
| `routes/campaigns.py` | 208 | 3 status axes + the 2 reports |
| `derive.py` | 197 | computed fields |
| `store.py` | 189 | in-memory dicts, logical clock, constants, id minting |
| `routes/drip.py` | 184 | schedules + steps |
| `services.py` | 178 | ledger, cascades A/B/C, proof expiry, resource release |
| `routes/proofs.py` | 155 | proof lifecycle |
| `routes/returns.py` | 148 | return events + reprints |
| `routes/templates.py` | 112 | templates + CASCADE A origin |
| `app.py` | 106 | app factory, error handlers, EADDRINUSE-tolerant boot |
| `errors.py` 102 · `envelope.py` 87 · `routes/ledger.py` 34 · `enums.py` 23 · `model.py` 20 | | |

**Endpoint completeness gate:** booted in-process, dumped `app.url_map`, normalised params, diffed against the scaffold's 78 `endpoints[]` — **declared 78, implemented 78, MISSING 0, EXTRA 0**; re-run after the final edit pass, still 0/0.

**Timestamp adjudication:** one renderer `store.render_instant()` for every server-written instant, format `YYYY-MM-DDTHH:MM:SS.mmmZ` (exactly 3 fractional digits, literal `Z`), fed only by the logical clock (`store.now()`, starting `2026-05-01T00:00:00Z`, moved only by `POST /_clock/set_current_utc`); no `datetime.now()`/`utcnow()`/`time.time()` anywhere. Caller-supplied instants are NOT echoed verbatim — the sole caller-supplied instant (`to_iso8601`) is parsed and `current_utc` re-rendered (HTTP-verified `...T00:00:00Z` → `...T00:00:00.000Z`). Derived instants use the same renderer (approve at `2026-05-01T00:00:00Z` → `expires_at 2026-05-31T00:00:00.000Z`; clock `2026-07-04T12:34:56.789Z` → `updated_at` matches while `created_at` stays). Calendar dates render bare `YYYY-MM-DD`.

**Closed enum-routing list (rung 7 → `ERR_INVALID_ENUM` 422):** `Account.status`; campaign `lifecycle_status`/`compliance_status`/`billing_status` when supplied as input; `pen_type`, `ink_type` (style); `envelope_style` (template create + PATCH); `dpv_confirmation_code` and `new_dpv_confirmation_code`; `job_kind`, `mail_class`, `eddm_rate_variant`; `mode` (dedupe run); `capacity_variant` (production run); `anchor_variant` (drip schedule); `ink_type` (ink lot); `status` (writing machine); `return_reason`. **No other field routes here.** Deliberate exclusions: every query-string filter never errors (`GET /mail/mail-jobs?status=NONSENSE` → 200, `total_count 0`); `limit`/`offset` out-of-range → `ERR_VALIDATION` (400); all other malformed values → `ERR_VALIDATION` at rung 6. Both branches HTTP-verified (5 enum 422s, 3 non-enum 400s).

**EADDRINUSE-tolerant boot:** socket created with `SO_REUSEADDR`, bound in a 40-attempt / 0.25 s retry loop, served via `werkzeug.serving.make_server(..., threaded=True, fd=sock.fileno())`. Simulation through `bash start.sh` with `kill -9` + immediate relaunch: **15 sequential rounds + 3 concurrent instances × 12 rounds = 51 rounds, 0 start failures.**

**The nine friction adjudications** (each carries a `# Adjudication of friction N` comment at the site):
1. §2.10 per-list counters → **unmailable-first precedence** (four counters mutually exclusive), keeping the list's partition invariant unconditionally true. (`derive.list_counts`)
2. §3.5 approve with stale `pinned_template_version` → **proceed**; rung 25 guards scheduling/committing only. (`routes/proofs.py:approve_proof`)
3. §3.5 proof collection read → **does NOT materialise** `APPROVED → EXPIRED`; only the single read and gate evaluations do. HTTP-verified. (`routes/proofs.py:list_proofs`)
4. §3.6 schedule with no anchor anywhere → **`ERR_VALIDATION`** at rung 6, keeping rungs 27–29 reachable with real dates. (`routes/jobs.py:_anchor_present`)
5. §3.6 dateless `PENDING` sibling in rung-30 gap check → **skipped**; both readings converge. (`routes/drip.py:_gap`)
6. §3.8 first draw on a `SEALED` lot landing exactly on 500 µL → **`SEALED → OPEN → DEPLETED` in one reservation**; staying `OPEN` strands the lot and makes `OPEN→DEPLETED` + `DEPLETED→OPEN` unreachable. (`routes/production.py:create_run`)
7. §3.8 dropping an addressed job with unfinished runs → **rung 17 `ERR_MAIL_JOB_INVALID_STATE`**; rung 19's `applies_to` covers only the four production-run endpoints. (`routes/jobs.py:_drop_state`)
8. §3.9 `FORFEIT` driving the balance negative → **allowed**; no rung guards the forfeit path and refusing would need an error the catalogue lacks. (`routes/lists.py:record_return`)
9. §3.9 `reprint_count` scope → **per-campaign**, evaluated against the cited `campaign_id` at rung 38 — strictly more reachable. (`derive.record_reprint_count`, `routes/returns.py:_cap`)

**Ladder fidelity:** one shared ordered pipeline (`Ctx.run()` walks rungs 1→41). 21 multi-violation HTTP checks confirmed first-rung-wins, including `rung 9 (hold) > 15`, `rung 9 > 17`, `rung 10 > 15`, `rung 11 (OCC) > 18`, `rung 12 > 16`, `rung 13 (EDDM) > 17`, `rung 21 > 22`, `rung 26 > 27`, `rung 33 > 35`, `rung 36 > 39`.

**Verification totals:** 5 smoke suites, **~190 HTTP assertions, 0 failures**, covering both pipelines, all three cascades, all four conservation invariants, all four OCC rules, both dual-variant pricing paths (provisional 243 → final 307 after household collapse; SATURATION 268 vs HDPLUS 307; the 553-cent reconciliation reproduced), all boundary inclusivities, and 39 of 43 error codes. Pure in-memory dicts, no seeding, no files. IDs are monotonic UUID-shaped strings.

**Orchestrator isolation check (Steps 5/6):** impl-agent transcript shows **0** reads of `test_suite/`/`test_helpers/` and **0** reads of either design index; test-agent transcript shows **0** reads of `implementation/`. Suite: 99 `def test_` == 99 `Design:` tags (50 Difficulty + 49 Corner), 0 skip/xfail; impl grep for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()` empty.




## Step 7: Run tests and iterate — 2026-08-08T19:32:00.000Z

All verification complete. No fixes or deletions were needed.

**Iterations run: 1.** The first 8-round sweep was clean and every mandated verification item passed, so no fix loop was entered.

- **Tests deleted:** none.
- **Fixes to `test_helpers/`:** none.
- **Fixes to `test_suite/`:** none.
- **Fixes to `implementation/`:** none.

### 1. Sweep integrity
All 8 `results.{1..8}.json` carry **99 individual test rows**, `total=99 passed=99 failed=0 errors=0 skipped=0`, every row `status=passed`. Sorted test-name list hashes **identical across all 8 rounds**; the 99 names are unique. Round durations 73–82 s. Each round log contains **exactly one `Killed`** line — the expected isolation swap, not a crash.

### 2. Suite shape
`grep -c 'def test_'` over `test_suite/` = **99**, equal to the runner's collected count. **Zero** `skip`/`skipif`/`xfail` markers anywhere.

### 3. Friction cross-check audit (per-friction verdict, re-derived)

| # | Friction | Verdict |
|---|---|---|
| 1 | per-list unmailable/duplicate precedence | **AGREEMENT-BY-CONSTRUCTION** |
| 2 | approval with stale `pinned_template_version` | **AGREEMENT-BY-CONSTRUCTION** |
| 3 | proof *collection* read materialising expiry | **CLEAN** |
| 4 | schedule with no in-home anchor anywhere | **CLEAN** |
| 5 | dateless `PENDING` sibling in rung-30 gap | **AGREEMENT-BY-CONSTRUCTION (vacuous)** |
| 6 | draw landing exactly on the 500 µL reserve | **AGREEMENT-BY-CONSTRUCTION** |
| 7 | rung reporting unfinished runs on a job drop | **CLEAN** |
| 8 | `FORFEIT` driving the balance negative | **CLEAN** |
| 9 | `reprint_count` per-campaign vs per-record | **CLEAN** |

**F1 — re-derived, not taken on trust.** `EIGHT_RECORD_ROSTER` = John/Jane Smith (100 Main St, 60601, DPV Y), Bob Jones, Carl Lee, Dana Fox, Eve Ray (Y), Frank Ash (D → RETAIL), Gus Vale (900 Ivy Pl, 60609, DPV N → UNMAILABLE). Under HOUSEHOLD: Smith{John head, Jane DUP_HOUSEHOLD}, all others singleton heads → automation **5**, retail **1**, duplicate **1**, unmailable **1**, mailable **6**, sum **8** = `record_count`. Gus's `household_key` `vale|900 ivy pl|60609` and `exact_key` collide with nobody, so he is never `DUP_*` — the only UNMAILABLE-tier record is never also a duplicate, and precedence-first == literal-independent counting. Under the EXACT re-run all 8 exact keys are distinct: 6/1/1/0, mailable 7, sum 8 — again identical. Additionally **no test asserts Gus's `dedupe_status`** (only his `deliverability_tier`). Same arithmetic reproduced for the campaign-level `deliverability_report` (test_09, 5/1/1/1/8).

**F2 — re-derived via ladder order.** `test_an_approval_carrying_a_pre_edit_template_version_is_stale` submits at pinned 1, patches the template to `version_no` 2, approves with `expected_template_version = version_before_edit`. §3.5 puts the rung-11 concurrency check **before** the proof's own status at rung 18, and rung 25 below both — so the OCC mismatch yields `ERR_STALE_VERSION` (412) under *both* readings, and neither permits a state change (asserted: proof still `SUBMITTED`, pinned still 1, job still `DRAFT`). The other approval path re-pins to 2 against a live `version_no` of 2 — no mismatch.

**F5 — re-derived, and vacuous.** Every drip step is created with an explicit anchor and each sibling's `computed_mail_date` is asserted before the next step is added, so the dateless-`PENDING` set is empty. MARKETING_MAIL transit 10: `06-15→06-05`; `06-16→06-06` gap 1 → `ERR_DRIP_GAP_TOO_SMALL`; `06-17→06-07` gap 2 → accepted. Eight-step ladder `06-15,17,…,29` → `06-05,07,…,19`, `steps[7] == 06-19`; the ninth at `07-01→06-21` is 2 clear, so only rung 31 can fire.

**F6 — re-derived.** `character_count` 400 × `ink_ul_per_1000_chars` 4.0 → `ceil(1.6) = 2` µL per piece. Thin lot **501** µL → `501 − 2 = 499`, a **strict** shortfall below the 500 reserve → `ERR_INK_INSUFFICIENT`, lot unchanged at 501/`SEALED`. Landing exactly on 500 would need a 502 µL lot; no roster produces it. No test asserts `status == "DEPLETED"`.

**F3/F4/F7/F8/F9 — evidenced by reading, not by absence of failures.** F3: `list_proofs` is defined in `api_client.py` but **called from zero tests**. F4: all 11 direct `schedule_mail_job` call sites pass `target_in_home_date`; every fixture caller passing `None` uses `stage="draft"`/`"proofed"`, so the anchorless body is never issued. F7: the only direct `mail_mail_job` call in a test is on an **EDDM** job; all three fixture drops are immediately preceded by `complete_production_run`. F8: balance is 500,000 − 306 = **499,694** before the 89-cent forfeit. F9: the reprint-cap test uses a single campaign and a single record.

### 4. Near-miss register — fair only by an incidental fixture value
1. **`lot_volume_ul=501`** (test_08:474) — 502 would land the draw exactly on the reserve → friction 6.
2. **`GUS_VALE`'s unique name/street/ZIP** — a second Vale at 900 Ivy Pl would make one record both UNMAILABLE-tier and `DUP_HOUSEHOLD`, splitting friction 1 and breaking `assert_list_partition_sums_to_record_count`.
3. **`expected_template_version=version_before_edit`** (test_05:339) — passing the current OCC version would clear rung 11 and put the approval squarely on friction 2.
4. **`build_addressed_scenario`'s conditional `schedule_body`** (fixtures.py:381-387) — any caller combining `target_in_home_date=None` with a stage beyond `"proofed"` lands on friction 4. Closest near-miss in the suite.
5. **`complete_production_run` at fixtures.py:416** — removing that one line makes every addressed drop a friction-7 case.
6. **`list_proofs` in `api_client.py`** — one added call after an approval plus a clock advance past `expires_at` lands on friction 3.
7. **`topup_cents=500_000`** — a seed between 306 and 395 would let the 89-cent forfeit drive the balance negative → friction 8.
8. **One campaign per reprint scenario** — a second campaign citing the same record turns test_09:186 into a friction-9 discriminator.
9. **Every drip step supplies an anchor** — one dateless step would activate friction 5.

### 5. Spot-checks
- **Response fields:** 129 distinct subscripted/`.get()` key names across `test_suite/`; **123 appear verbatim in `PRD.md`**. The 6 that do not are keys of the local `TEST_USERS` header dictionary, not API fields.
- **Numeric literals:** independently re-derived — `6×31.8=190.8→191` + `1×51.6→52` = **243**; `5×51.0=255`+52 = **307**; `12×22.3→268`; `12×25.6→307`; `5×22.3→112`; settlement `250+ceil(0.08×307)=275`, `307+275=582`, `floor(0.05×582)=29` → **553**; `250+ceil(0.08×51)=255` → **306**; `250+ceil(0.08×112)=259` → **371** (5 pieces, below the 6-piece credit floor); reconciliation `306−0+89=395`; ink `20000−2=19998`, `20000−5−5=19990`; escrow `500000−306=499694`, `−89=499605`; slot minutes `ceil(1200/4000)=1 + 12 = 13`.
- **Ordering:** 9 integer-index subscripts inside asserts; `steps[7]` indexes a locally-built Python list, `draws[0]`/`forfeits[0]`/`refunds[0]` each preceded by `assert len(...) == 1`. No assertion depends on an unstated server ordering rule.
- **Implementation hygiene:** `grep -rniE "sqlite|json\.dump|pickle|/tmp|datetime\.now|utcnow|time\.time\(\)|shelve"` over `implementation/` returns **empty**. All nine `# Adjudication of friction N` comments are present and sited.

Neither known implementation-generator bug vein surfaced: no timestamp-rendering failure and no enum-routing failure appeared in any round.

**Orchestrator independent zero-fix verification:** all 8 `results.N.json` re-parsed independently → 99 rows each, `passed=99 failed=0`, status set exactly `{'passed'}`, sorted name-list hash `0d7194f9aa` identical in all 8; `find test_suite test_helpers implementation -newer results.1.json` **empty** (nothing touched after the sweep); exactly one `Killed` per round log; independent route diff (scaffold `endpoints[]` vs in-process `app.url_map`, params normalised) → **78/78, 0 missing, 0 extra**.

## Step 8: Finalize PRD — SKIPPED — 2026-08-08T19:34:00.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. Per the skip condition there is no `<step_7_diff>` to patch against, so `PRD_FINALIZED.md` is not produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-08T19:52:00.000Z

`workspace/PRD_COMPLETED.md` written as a minimal in-paragraph patch over `PRD.md`.

**Counts** — lines unchanged **559 → 559** (no new paragraphs, no new sections); chars **116,414 → 136,748** (**+20,334**). `^#` heading list verified identical by diff. **9/9 frictions converted.** 45 changes total: **33 ambiguity-pins**, **12 mismatch-revisions**.

### The nine frictions (all `revise`)
- §2.10 — mismatch — per-list counters **inherit unmailable-first precedence**; ordered unmailable→duplicate→automation→retail, first bucket wins — `derive.py:64-94`
- §3.5 — mismatch — approval **proceeds** on a stale `pinned_template_version`; rung 11 is the only template guard — `routes/proofs.py:114-123`
- §3.5 — mismatch — the **collection** read does *not* materialise `APPROVED → EXPIRED`; only the single read and the gate do — `routes/proofs.py:68-73`
- §3.6 — mismatch — dateless schedule → `ERR_VALIDATION` at **rung 6**, pre-empting gate/state/approval rungs — `routes/jobs.py:164-192`
- §3.6 — mismatch — dateless `PENDING` sibling skipped; but a step *created* `PENDING` still holds dates and participates — `routes/drip.py:126-134`
- §3.8 — mismatch — a draw landing exactly on 500 µL carries `SEALED → OPEN → DEPLETED` in one reservation — `routes/production.py:70-78`
- §3.8 — mismatch — unfinished runs report `ERR_MAIL_JOB_INVALID_STATE` at **rung 17** (three sub-conditions) — `routes/jobs.py:337-349`
- §3.9 — mismatch — a `FORFEIT` **may** drive `permit_balance_cents` negative — `routes/lists.py:280-288`
- §3.9 — mismatch — `reprint_count` is **per-campaign**, derived at read time from `last_mail_job_id`'s campaign — `derive.py:112-136`, `routes/returns.py:127-132`

### Highest-yield finds no test could catch
- §2.1 — insert — ambiguity — **no collection endpoint applies the account-scope check**; cross-resource ownership never compared — `ladder.py:168-175`
- §3.3 — revise — mismatch — the 100,000-record ceiling is **documentary; nothing enforces it** — `store.py:64` (unreferenced)
- §3.1 — insert — mismatch — `Account.status` is stored and returned but **consulted by nothing**; no endpoint ever changes it — `serial.py:21-33`
- §3.4 — insert — mismatch — **no rule outside rung 15 reads `lifecycle_status`**; a `DRAFT` campaign's jobs commit and mail normally
- §3.3 — insert — ambiguity — CASS/dedupe bump a **record's** `version` only when a screening axis actually changed (the list always bumps) — `routes/lists.py:27-31`
- §3.6 — revise — mismatch — **nothing re-applies `PENDING → SCHEDULED`**; the "reversible loop" is one-way in code — `services.py:76-81`
- §3.6 — insert — mismatch — release evaluates step-state *then* job-state **both at rung 20**, inverting the 17-vs-20 ordering — `routes/drip.py:179-184`
- §3.7 — revise — mismatch — `refunded_postage_cents` is **ledger-derived and cumulative**, not "the amount returned" — `serial.py:143`
- §3.4 — revise — ambiguity — a route selection rewrites the job's `billable_piece_count` too, and later refreshes **never bump the selection's `version`** — `routes/jobs.py:380-383`, `calc.py:92-101`
- §3.5 — insert — ambiguity — "most recent approval" = max `(approved_at, id)`; `approved_at` survives `SUPERSEDED`/`EXPIRED`, so rung 24 always clears first — `services.py:42-58`
- §3.5 — insert — mismatch — the job advances **only from `DRAFT`**; a later approval leaves `status`/`pinned_template_version`/`version` alone — `routes/proofs.py:125-129`
- §3.5 — insert — ambiguity — a proof's `template_id` need not equal its job's; the gate reads the proof's template — `routes/proofs.py:53-54`
- §2.5 — insert — ambiguity — a template edit resolves to **many** campaigns: all compliance axes before any billing axis — `ladder.py:250-269`, `routes/templates.py:70-82`
- §2.5 — insert — ambiguity — every mailing-list write resolves to **no** campaign and is never gated
- §2.6 — insert — ambiguity — rung-6 shape rules: non-object body, `null`-as-omitted, unknown fields ignored, `permit_number` the only emptiness check
- §3.2 — revise — ambiguity — the `version_no` bump tests **by value**, not by key presence; `null` fields ignored — `routes/templates.py:98-110`
- §2.9 — insert — ambiguity — three of rung 13's four operations are structurally unreachable (EDDM jobs never acquire records)
- §3.8 — insert — mismatch — `spoiled_piece_count` is stored and read back but consulted by nothing; quarantine/void-run `reason` are validated then **discarded**
- Plus pins on: monotonic id ordering (`store.py:117-120`), `limit`/`offset` → `ERR_VALIDATION`, filters never validated, 404-not-405 for unknown routes/methods, fixed ledger `reason` literals, top-up answering **201** with the account, `pen_type`/`envelope_style`/`body_text` consulted by nothing, unvalidated `zip5`/`state_code`, past `target_in_home_date` accepted at job creation, refused quotes writing nothing, `step_count` 0 on a cancelled schedule, void's exhaustive-clear list and its deliberate omissions, ink-lot `version` bumps on reserve/void, machine `version` never past 1, `UNASSIGNED` records breaking the partition identity, per-job double-counting in the deliverability report, and `ERR_INTERNAL`/500 noted in §5.

**Orchestrator independent verification:** `diff` of all `^#` headings PRD vs PRD_COMPLETED **empty** (no sections added); line count 559 → 559; `find test_suite test_helpers implementation -newer results.1.json` **empty** again after Step 9 (the completeness pass touched no code or tests); `PRD_FINALIZED.md` correctly absent; all 8 `results.N.json` retained.

## Pipeline complete — 99/99 × 8 rounds, 0 fixes, 0 deletions.
