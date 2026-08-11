# Worklog — task_0946_mobile_knife_tool_sharpening

Scenario (verbatim):
```
946. Mobile Knife & Tool Sharpening (route): service request & item type, van route & dispatch, per-item/subscription pricing, restaurant/salon standing route, drop-off & locker option, quality/warranty, inventory (loaner/rotation), billing
```

Difficulty: **beyond-Expert** (user asked "generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-09T10:15:00.000Z

Created `tasks/task_0946_mobile_knife_tool_sharpening/` and `tasks/task_0946_mobile_knife_tool_sharpening/workspace/`. Index 0946 = highest existing in `./tasks/` (0945) + 1.

## Step 2: Generate scaffold — 2026-08-09T11:25:00.000Z

Done. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_0946_mobile_knife_tool_sharpening/` and verified.

### Structural counts

| Dimension | Value |
|---|---|
| Entities (§1.1) | **19** |
| Endpoints (§1.5) | **85** (53 POST, 30 GET, 1 PATCH, 1 DELETE) |
| Error codes (§1.6) | **72** |
| Calculations (§1.3) | **16**, of which **8 dual-variant** |
| Status axes / state machines (§1.2) | **13** (74 transitions), of which **10 non-linear** |
| Validation rungs (§1.4) | **57**, plus a 9-entry `gate_precedence` block |
| OCC rules (§1.2.1) | **3** |
| Conservation invariants | **6** (explicit `conservation_invariants` block) |
| Max cascade depth | **6** |
| Declared global constants | **46**, zero undeclared |
| §1.8 instances | **25** across all 9 `rule_id`s (min 2 each) |
| §1.9 instances | **85** (77 with full recipes + 8 `excluded_because` stubs) |

Files: `SCAFFOLD.yaml` (3.9k lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2.4k), `SCAFFOLD_CORNER_DESIGN.yaml` (4.5k). Neither design key appears inside `SCAFFOLD.yaml`.

### Design shape

`api_prefix: /sharpening`. Quota/allocation primary + pricing-engine secondary. Two scarce capacity pools (van service-minutes, shop bench-minutes) competed for by three intake channels (VAN_ROUTE / LOCKER / REWORK), with money layered on as an allowance-vs-overage pricing engine. Peer roles with segregation of duties (the technician who assessed an item may not adjudicate its warranty claim).

**Non-linear axes (10):** RequestItem carries two parallel axes on one row (`service_status` with a `DELIVERED → REWORK_QUEUED → DELIVERED` loop, `custody_location` with a `CUSTOMER → VAN → BENCH → DELIVERED → CUSTOMER` cycle plus a LOCKER branch); ServiceRequest carries `status × billing_status` in parallel; RouteStop has a `SCHEDULED → SPILLED → SCHEDULED` re-entry capped at `SPILL_MAX_HOPS`; Subscription has `ACTIVE ↔ PAUSED` plus three `ACTIVE → ACTIVE` self-loops; LockerCompartment cycles `AVAILABLE → ASSIGNED → OCCUPIED → AVAILABLE` with an `OCCUPIED ↔ ASSIGNED` sub-loop; LoanerUnit cycles `IN_STOCK → ISSUED → INSPECTION → IN_STOCK`; WarrantyClaim has a capped `DENIED → SUBMITTED` retry; Invoice self-loops on `PARTIALLY_PAID`; Account is `ACTIVE ↔ SUSPENDED`.

**Depth-6 cascade** (warranty approve): claim APPROVED → item REWORK_QUEUED + custody back to CUSTOMER → REWORK ServiceRequest + pre-assessed clone opened → workmanship credit emitted onto a DRAFT invoice (minted if absent) → invoice re-totalled → original request's billing axis reaches CREDITED. Second cascade (depth 4, different trigger): deliver → item DELIVERED → LoanerIssue RETURNED → LoanerUnit INSPECTION → RETIRED at cycle ceiling.

**Rule 2 modes exercised:** (a) rush-floor over overage-discounted base with a nested `max`; (b) tax pinned as one `round_half_up` over the aggregate taxable subtotal — a 2×900 invoice makes per-line (130) and aggregate (131) disagree; (c) the dispatch spill loop, where `committed_minutes_final` decides which stop spills and spilling changes the set the value is computed over.

### Mandatory gates

- **A. Incremental writes** — built in 12 bounded Write/Edit increments; nothing emitted in one giant call.
- **B. YAML lint** — `python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" SCAFFOLD.yaml SCAFFOLD_DIFFICULTY_DESIGN.yaml SCAFFOLD_CORNER_DESIGN.yaml` → **all three parse**. One real offender was found and fixed: unquoted `$.data[0].id` capture paths inside flow mappings (`[` is a flow indicator) — all such captures are now quoted.
- **C. Constants** — **46 declared, zero undeclared.** Scripted scan of every `ALL_CAPS_TOKEN` across all three files against `global_constants` ∪ error ids ∪ enum/state vocabulary left exactly three residuals, all legitimately non-constants: `ALL_CAPS` (a comment), `BLADE_BASIC` (a PlanTier code literal in fixtures), `ERR_XXX` (the §1.0 envelope template).
- **E. Worked-example arithmetic** — every numeric assert was recomputed in Python against the declared formulas and constants (2025→1721 discount, `max(500, 344)`→2221, tax 2721→197, total 3318; 1800→131 not 130; 9000×61/30→18300, tax 1327, total 19627; 12765→925/13690; spill 85→65; late fee `min(2500, 16×250)`→2500; delta exactly 1000 at list 1666 and 1001 at list 1668).
- **F. Ladder ordering** — all 57 rungs numbered with an explicit `pre_empts:` on each, plus a `gate_precedence` block placing GATE_AUTHENTICATION(1), ROLE(2), PATH_EXISTENCE(3), REQUEST_SHAPE(4–7), OWNERSHIP(8), **ACCOUNT_STATUS(9)**, BODY_EXISTENCE(10), **CREDIT_LIMIT(11)** and **OCC_VERSION(12, deliberately before every state precondition)**.

### Reachability audit (gate D)

Checked both ways — no earlier gate pre-empts, and the declared numbers admit the branch.

**All 8 dual-variant calculations have both branches reachable and exercised.** The riskiest was `run_committed_minutes` DISPATCH_FINAL, whose "use assessed minutes" branch was initially unreachable (assessment requires BENCH custody, which happens after dispatch). Fixed at the design level: the warranty rework clone is created already carrying `assessed_damage_tier = ROUTINE_HONE` (declared tier copied from the original's assessed tier), so a REWORK stop legitimately carries assessed minutes before its run is dispatched.

**Three rungs were found unreachable and repaired:**
1. `ERR_NOT_ASSESSED` at rung 20 was algebraically dead — `assess` sets `service_status` and `assessed_damage_tier` together, so rung 14 always pre-empted it. Rung 20 was repurposed to a genuinely reachable, domain-useful check (`BenchDay.bench_date` must equal the logical clock date, `ERR_BENCH_DAY_DATE_MISMATCH`), deliberately placed above the bench-capacity rung.
2. `ERR_SUBSCRIPTION_NOT_ACTIVE` at rung 17 was pre-empted by rung 14 on skip/cadence/advance-cycle (all declare `from: ACTIVE`). Re-scoped to `POST /service-requests` supplying a CANCELLED `subscription_id`, and the pre-emption is documented in the rung text.
3. `ERR_CLAIM_ITEM_ACCOUNT_MISMATCH` at rung 28 was pre-empted by the rung-8 ownership gate. Rung 8 now carries an explicit carve-out (on `POST /warranty-claims` the acting owner *is* the scope).

**One live-lock found and fixed:** rung 9's account gate would have blocked `POST /accounts/{id}/reinstate`, making SUSPENDED terminal. The gate now exempts suspend, reinstate and `PATCH /accounts/{id}`.

**Deliberately partially pre-empted, documented in the scaffold:** `ERR_INVOICE_NOT_PAYABLE`'s *status* clause is unreachable (rung 14 rejects a DRAFT invoice first); its reachable trigger is the **credit-memo** case — an ISSUED invoice whose `amount_due_cents` is negative, produced by a pause proration. That path is exercised in §1.9.

**Enum closure:** scripted check — every enum value declared in a state-axis `constraints:` is written by at least one transition or is the initial state. Zero unproduced values.

**Error coverage:** all 72 error ids are referenced by at least one design-file instance. `ERR_ITEM_LIMIT_EXCEEDED` was initially uncovered because `MAX_ITEMS_PER_REQUEST` was 40 (a 41-call chain); the constant was lowered to 8 and a §1.9 instance added.

### Scaffold lint (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    85
  §1.1 entities declared:     19
  §1.8 instances scanned:     25
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1094

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional scripted checks beyond the linter, all passing: **zero unbound `${var}` placeholders** across 1094 calls in both design files (including asserts); **zero unresolvable `grounds:` references** (calculations, errors, validation priorities, concurrency rule ids, roles, entity fields, endpoints, state-machine entities); **109 instance names, all unique** across the union of both files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name.

Two pre-existing artifacts (`worklog.md`, `workspace/`) were already in the task directory and were left untouched.

**Orchestrator independent verification:** `yaml.safe_load` of all three files OK; `SCAFFOLD.yaml` top keys contain no `*_design` key; endpoints=85, entities=19, errors=72 counted from the parsed YAML.

## Step 3: Copy shared files — 2026-08-09T11:26:00.000Z

`cp ./INSTRUCTION.md tasks/task_0946_mobile_knife_tool_sharpening/workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-08-09T11:47:00.000Z

PRD written to `workspace/PRD.md`.

### Size
**613 lines, 18,157 words.** Structure: §1 intro (3 paragraphs), §2 with 11 subsections, §3 with 10 subsections, §4 endpoint table (4 columns), §5 error table (2 columns). Document ends at the §5 table — no audit footer.

### §B coverage audit (all mechanically verified against the scaffold)

| Item | Count | Status |
| --- | --- | --- |
| Endpoints in §4 table (method + path + description + roles) | 85 / 85 | PASS |
| Error codes in §5 table | 72 / 72 | PASS |
| Error codes whose raising condition appears in §1–§3 prose (not just the table) | 72 / 72 | PASS |
| Validation rungs, numbered 1–57 in declared order, each with condition + error + HTTP status + `applies_to` + explicit "pre-empts rungs N–57" | 57 / 57 | PASS (sequential, verified) |
| `gate_precedence` gates, each pinned to its numbered rung | 9 / 9 | PASS |
| Calculations with full formula, rounding mode + order | 16 / 16 | PASS |
| Dual-variant calculations with an explicit branch selector | 8 / 8 | PASS |
| Status axes with every transition, trigger and preconditions | 13 / 13 | PASS |
| State transitions rendered in literal `FROM → TO` form | 74 / 74 | PASS |
| Declared constants given with numeric values | 46 / 46 | PASS (no threshold is named without its value) |
| OCC rules (endpoint + `expected_*_version` + error + 412 + why-not-a-state-precondition) | 3 / 3 | PASS |
| Conservation invariants with formula + compensating pair | 6 / 6 | PASS |
| Cascades leg-by-leg incl. non-firing legs | 2 (warranty depth-6, delivery depth-4) | PASS |

**Hard contracts.** Contract 1 (field-name coverage): 137/137 entity fields, 72/72 request-body identifiers, 36/36 query params — 0 missing. Contract 2 (rule coverage): all categories walked, 0 gaps. Contract 3 (§3 path purity): 950 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path. §2.2 emitted byte-identical to the canonical source.

### Scaffold ambiguities and how they were resolved in prose

1. **Client-supplied `channel: REWORK`.** The scaffold constrains `channel` to "one of VAN_ROUTE, LOCKER, REWORK; REWORK may not be supplied by a client", but `REWORK` *is* a declared enum member, so rung 5 (`ERR_INVALID_ENUM`) does not naturally catch it. Resolved: the PRD states explicitly that a client supplying `REWORK` is refused with `ERR_VALIDATION` at the request-shape gate, "because the value is well formed and simply not client-writable."
2. **Conditionally-required `locker_site_code`.** Scaffold says "required when channel is LOCKER, ignored otherwise" with no error named. Resolved as a missing-required-field failure → `ERR_VALIDATION` (rung 4), stated inline.
3. **`PlanTier.code` uniqueness.** The scaffold declares "unique across PlanTier" but supplies no rung and no error code for a duplicate. No enforcement was invented; the PRD says the code is "expected to be unique across plan tiers" without attaching an enforcement, matching the scaffold's actual (unenforced) state.
4. **Warranty credit line when `credit_basis_cents` is 0.** The scaffold is silent on whether link 4 is skipped. Resolved in favour of always writing the line (at zero) and said so explicitly, on the grounds that the line is the audit record — with link 5's recompute then producing no money change.
5. **Response shape of `locker-assign`.** The endpoint is invoked on a service request but the scaffold's `output` is `LockerCompartment`. Since §4's four-column table cannot carry output shapes, this is called out twice — in §3.6 and in the §4 preamble — alongside the two other deviations (clock-set returns `current_utc`; the statement returns its own computed object).
6. **`ERR_INVOICE_NOT_PAYABLE` reachability.** The scaffold notes rung 14 pre-empts the status half. The PRD reproduces that reasoning verbatim in prose so an implementer knows the reachable trigger is an issued credit memo with non-positive `amount_due_cents`, not a `DRAFT` invoice.
7. **Item-`version` bump granularity.** §2.4 states versions bump per row actually changed, per request, and that rejected requests bump nothing — needed because three endpoints are OCC-guarded on exactly that observable.

## Step 5: Generate unit tests — 2026-08-09T13:05:00.000Z

Complete. Final verification run cleanly across every audit.

### What was generated

**`test_helpers/`** (9 files) — `types.py` (13 status enums + TypedDicts, with `InvoiceLine` / `Payment` / `AllowanceLedgerEntry` carrying only `id` + `created_at`), `api_client.py` (one method per each of the 85 endpoints), `api_errors.py` (all 72 error ids + HTTP map registered with the framework), `assertions.py` (per-entity assertions, the six conservation-invariant checkers, and `assert_same_instant` / `parse_instant` — every timestamp assertion in the suite goes through it), `constants.py`, `factories.py`, `test_users.py` (opaque-role constants plus `make_account_owner_headers` / `make_technician_headers`; two distinct technicians are producible for the segregation-of-duties rung), `fixtures.py` (~55 primitives + Tier 1–4 composites: `build_config`, `stage_request`, `route_to_van`, `route_to_bench`, `work_and_deliver`, `setup_delivered_van_visit`, `setup_locker_deposited/delivered`, `setup_cadence_upgrade_invoice`, `setup_paused_credit_invoice`, `setup_claim_ready`).

**`test_suite/`** — `conftest.py` + 10 domain-named files, **127 tests**: **50 from queue A** (25 difficulty instances × 2) and **77 from queue B** (77 non-stub corner instances × 1).

### Audit results

- **Skipped instances: 0.** Every one of the 102 non-stub instances passed the PRD-first two-condition filter — this PRD states every rung, formula, constant and side-effect verbatim. The 8 `excluded_because:` corner stubs were checked: all 8 `difficulty_instance` cross-references resolve to real names, and none were translated.
- (i) every test carries exactly one `Design:` line, and it is the last line of the docstring — verified by AST walk, 0 problems; (ii) `def test_` count 127 == Design-tag count 127; (iii) `grep -rnE "pytest\.mark\.(skip|skipif|xfail)"` over `test_suite/` is empty.
- All 25 difficulty instances have ≥2 tests, all 77 corner non-stub instances have ≥1; no tag points at a non-existent instance.
- **234 quoted PRD spans checked against a whitespace-normalised `PRD.md` — 0 failures.**
- `pytest --collect-only` collects all 127; pyflakes reports no undefined names and no unused imports in `test_suite/`; no "scaffold" references anywhere in the emitted code.

### PRD points judged ambiguous (assertion narrowed, instance still tested)

1. **`Technician.certifications` default.** Corner instance `create_account_applies_declared_defaults_and_system_fields` also asserts `certifications == []` for a technician created with only `full_name`. PRD says the array "may be empty" but never names a server-side default for an omitted field — a silence-pattern `default-value`. That one side-assertion was dropped; the instance's principal claim (the five account defaults + `version` 1) is fully asserted.
2. **No `GET /item-class-specs/{id}`.** The duplicate-spec instance asserts `ItemClassSpec.list_price_cents == 900` after the rejection, but §4 declares no read endpoint for specs. Asserted on the surviving creation response instead.
3. **`cycle_index` of the `EXPIRED` row at cycle close.** PRD says each ledger row records "the `cycle_index` it was booked against" but does not say whether the close-out expiry belongs to the closing or the opening cycle. The advance-cycle test asserts the row count and the `GRANTED, EXPIRED, GRANTED` kind sequence, not the `cycle_index` of those rows.

### One design-index defect found and worked around

`monthly_rollup_spends_the_allowance_across_the_whole_cycle` places two requests on **one** run; a naive per-request "route → dispatch" helper would dispatch the same run twice. Both stops are now added while the run is `PLANNED`, dispatched once, then arrived/picked-up/benched in turn. `route_to_van`/`route_to_bench` no longer accept a pre-existing run, so the mistake cannot recur.

`workspace/implementation/` was never read.

**Orchestrator containment note:** Step 5 finished while Step 6 was still writing, so `test_suite/` and `test_helpers/` were physically `mv`-ed out of the task tree into a scratchpad holding directory until Step 6 exited, then moved back — the impl generator could not read them even accidentally.

## Step 6: Generate implementation — 2026-08-09T13:22:00.000Z

Implementation complete and verified.

### Deliverable

`workspace/implementation/` — **20 Python modules, 5,108 lines**, plus `start.sh` and `requirements.txt`. Layered as: `constants` / `errors` / `clock` / `store` / `envelope` / `ladder` (the 57-rung walker + request-shape DSL) / `calcs` (16 calculations) / `serializers` (live aggregates) / `services` (gates, selectors, cascades) / nine `routes_*` blueprints / `app_factory` / `app`.

### B. Endpoint completeness gate (numeric, (METHOD, PATH) pairs)

**85 declared / 85 routed / MISSING 0 / EXTRA 0.** Diffed as sets of pairs, not paths — the scaffold has three shared paths under two methods each (`/accounts/{id}` GET+PATCH, `/route-stops/{id}` GET+DELETE, `/locker-compartments` POST+GET), which a path-only diff would have collapsed.

### C. Timestamp three-case adjudication (stated, uniform)

1. **Server-generated** → `YYYY-MM-DDTHH:MM:SS.mmmZ` (exactly three fractional digits, literal `Z`): `created_at`, `updated_at`, `completed_at`, `delivered_at`, `issued_at`, `returned_at`, `applied_at`, `paused_at`, `hold_expires_at`, `last_released_at`, `api_request_timestamp`.
2. **Caller-supplied** → **echoed verbatim, never re-rendered**. The only caller-supplied instant is `to_iso8601`; `current_utc` returns the caller's exact string, and the un-set default reads the PRD's literal `2026-05-01T00:00:00Z`. (PRD §2.4's three-digit rule is stated about the common resource fields; §2.5 states the default's literal form.)
3. **Derived-from-an-instant** → rendered under rule 1, because every derived stamp (`due_at = issued_at + 14d`, `hold_expires_at = clock + 72h`, the re-stamped `delivered_at`) derives from the **clock instant** (server state), never from a caller string. The recurring `.000Z`-vs-`Z` mismatch therefore cannot arise: verified `issued_at`/`due_at` both render `…T00:00:00.000Z`.

### D. Enum-routing iff-list (closed)

A field routes to `ERR_INVALID_ENUM` (422) **iff** its name is in exactly: `account_type, zone_code, billing_mode, cadence, allowed_cadences (members), item_class, declared_damage_tier, assessed_damage_tier, channel, priority, required_certification, price_tier, min_locker_size, size, grade, requested_grade, method, source, status, billing_status, custody_location, service_status, kind` **and** the value is a *string* that is not a declared member. Named exclusions:
- **`certifications` members** — deliberately *not* on the list → `ERR_VALIDATION` (400) at rung 4. Verified.
- **`channel: "REWORK"`** — well-formed but not client-writable → `ERR_VALIDATION` at the request-shape gate (§3.3).
- **Any listed field with a non-string JSON type** → `ERR_VALIDATION` at rung 4 (wrong type is a shape failure).
- **Numerics that parse but are out of range** → `ERR_VALUE_OUT_OF_RANGE`.
Query-string filters (`status`, `channel`, `kind`, `source`, …) route by the same rule, at rung 5 — i.e. *before* pagination at rung 7 (verified: `?status=BOGUS&limit=0` → 422).

### E. Boot latency — **measured pre-bind 0.1 ms** (max across 10 kill -9/relaunch cycles), retry ceiling **280 attempts × 50 ms ≈ 14 s**

`main()` binds and listens before importing Flask or any app module, then hands the held fd to `werkzeug.serving.make_server(..., fd=sock.fileno(), threaded=True)`. Entry-module imports are stdlib-only. 10/10 restarts succeeded, ready in 544–721 ms. `start.sh` reads `$PORT`, binds `0.0.0.0`, guards `pip install` on a cheap `import flask`, and `exec`s in the foreground.

### F. In-memory only, no seeding

`grep -nE "sqlite|open\(|json\.dump|pickle|/tmp|shelve|\.write\("` returns **nothing that persists state** — the only hits are `sys.stderr.write` (one boot log line) and the function names `_warranty_window_open` / `_skip_window_open`. Store is plain dicts, empty on every boot; no `seed_*`.

### Verification

Three smoke suites (~200 assertions) all green: full van-route lifecycle, locker channel (assign → deposit → bench → deliver → release, plus expire-hold/abandon), loaner substitution + inspection chain, the six-link warranty cascade, PER_VISIT and MONTHLY_ROLLUP invoicing (allowance ranking, overage discount, RUSH floor, single-rounding tax = 1341¢ on 18500¢), OCC 412s, suspension outranking an unknown FK, credit gate, proration (+11000 / −18083), cadence/skip/pause/resume/advance-cycle, spill→reschedule to two hops, the hold-expiry-beats-wrong-code trap, and the compartment selector's 3-way adjudication. Conservation checked directly: stop add→delete returns `booked_service_minutes`/`scheduled_stop_count`/`committed_minutes_provisional` to 0/0/0; invoice create→void returns `allowance_remaining` 4→2→4.

### H. Reachability hypotheses — claims to verify by reading the code

1. **`ERR_STOP_ACCOUNT_MISMATCH` on reschedule is likely unreachable.** The receiving-run selector already filters on `zone_code == account.zone_code`, so a zone mismatch yields an empty pool → `ERR_NO_ELIGIBLE_RUN` (rung 50) before rung 27 could fire. Implemented anyway.
2. **The RESTORED-on-decline branch is likely unreachable.** `allowance_applied` is only set at invoicing (request `COMPLETED`), but decline requires the request `IN_SERVICE` (rung 16). Implemented anyway.
3. **Reschedule after a *dispatch-loop* spill is blocked** by the literal reading of rung 15 ("PLANNED for … reschedule", parent = `stop.route_run_id`, which the dispatch loop leaves pointing at the now-`DISPATCHED` run). Explicit spills from `PLANNED` runs — the main path — reschedule fine. Flagged as the literal-PRD choice.
4. **`ERR_DUPLICATE_INVOICE` (rung 48) is reachable only via PER_VISIT** (the rollup scope pre-filters on `UNBILLED`); the `UNBILLED` test was deliberately *not* folded into rung 14, or rung 48 would be dead everywhere.

### Other adjudications worth downstream review

- **Technician ownership**: run-attachment (`X-User-ID == run.technician_id`) enforced on the two mutating run-attached ops (`arrive`, `pickup`); every other Technician endpoint requires only that `X-User-ID` resolves to a `Technician` row (§2.1's concrete testable claim). GETs are not run-scoped.
- **`sequence_index` is re-sequenced on every line append** using the pinned kind order of §3.10, so the ordering contract holds even when a proration credit, late fee and warranty credit land on the same DRAFT invoice in an arbitrary order. Trade-off: it mutates a field on an otherwise append-only record.
- **Decline clears `bench_day_id`** — the only way to satisfy both "decline releases the item's bench minutes" (§3.7) and §2.10's formula (`bench_day_id` names the day *and* custody is `BENCH`), since no custody transition is declared for a declined item.
- **List endpoints are not account-scoped** for `AccountOwner` (no PRD prose demands filtering); single-resource GETs *are* ownership-checked.

**Orchestrator independent verification:** booted the app in-process and diffed `app.url_map` against the scaffold's `endpoints[]` as **(METHOD, PATH) pairs** — declared 85 / routed 85, MISSING 0, EXTRA 0 (the only extra rule is Flask's built-in `GET /static/{}`). `grep -rnE "sqlite|json\.dump|pickle|shelve|/tmp/"` over `implementation/*.py` → empty. Tests restored to the tree: 127 `def test_`, 127 `Design:` tags, 0 skip/xfail/skipif.

## Step 7: Run tests and iterate — 2026-08-09T14:35:00.000Z

Task complete. Final sweep is clean.

### Summary

**Iterations run:** 2 full 8-round sweeps, wave size 2 (host carried 2 foreign prd-bench pipelines at start, load ~4). The **first sweep passed 127/127 in all 8 rounds with zero fixes** — this is a clean first-sweep pass. The second sweep re-confirmed the tree after a mutation experiment.

**Tests deleted:** none. STEP 1 deletion is scoped to the union of failing tests, and that union was empty across all 8 rounds.

**Fixes applied to `test_helpers/`, `test_suite/`, `implementation/`:** none. No failure ever occurred, so no fix was warranted.

#### Verification that the clean pass is real (not an artifact)
- **Isolation falsification.** A control run with `--isolation none` scores only **23/127** (104 fail, mostly `ERR_DUPLICATE_ITEM_CLASS_SPEC` as tests rebuild the same world on a shared server). Passing under `per-test-server` but collapsing under `none` is positive proof the per-test reset genuinely happens.
- **Collection integrity.** 127 defined = 127 collected = 127 passed, byte-identical test-name set across all 8 rounds, `skipped=0`. No silent skip or `xfail`.
- **Route completeness.** Implemented `(method, path)` routes = **85/85**, exactly matching the scaffold with no extras — no Step-6 partial-write gap.
- **No seeding/persistence.** `store.py` is plain in-memory dicts, reset on boot; no SQLite/JSON/`/tmp` anywhere.

#### The four hand-down hypotheses — all four CONFIRMED, none refuted
1. **`ERR_STOP_ACCOUNT_MISMATCH` on reschedule is unreachable — CONFIRMED.** `services.select_receiving_run` skips any run where `run["zone_code"] != account["zone_code"]`, so every candidate matches by construction; the rung-27 recheck at `routes_route.py:322` is dead, and a genuine mismatch empties the pool into `ERR_NO_ELIGIBLE_RUN`. (The sibling at `routes_route.py:163`, on stop *addition*, is reachable.)
2. **RESTORED-on-decline is unreachable — CONFIRMED.** `allowance_applied` is set true only at `routes_billing.py:189` during invoicing, which requires the request `COMPLETED`; decline requires `IN_SERVICE` (`routes_requests.py:585`). The states are disjoint, so the restore block at `routes_requests.py:592-602` cannot fire.
3. **Reschedule after a dispatch-loop spill is blocked — CONFIRMED.** Spill sets `spilled_from_route_run_id` but leaves `route_run_id` pointing at the source run, and `_parent_run` reads `route_run_id`; a dispatch-loop spill therefore finds a `DISPATCHED` parent and hits `ERR_RUN_NOT_MUTABLE`. Explicit spills from `PLANNED` runs reschedule fine.
4. **`ERR_DUPLICATE_INVOICE` reachable only via PER_VISIT — CONFIRMED.** In `MONTHLY_ROLLUP` the covered set is pre-filtered on `billing_status == "UNBILLED"`, so the rung-48 loop is vacuous there; only PER_VISIT's `covered = [named_request]` can carry an `INVOICED` request past the rung-13/14 checks (which test `CREDITED` and `COMPLETED`, not `INVOICED`).

#### Near-misses (tests that pass, but not by construction)
One claim was **empirically falsified rather than argued**, which is the strongest finding:

- **Segregation of duties is tested on approve only.** Mutating `routes_warranty.py:235-236` to disable the deny-side guard and re-running a full round: **127/127 still passed**. PRD §3.9 explicitly says "The rule applies identically to approval and to denial — there is no asymmetry where a self-denial would be permitted", yet every `deny_claim` call uses the non-assessing technician. One assertion of `ERR_SEGREGATION_OF_DUTIES` on deny would close it. (File restored byte-identical, md5 `abfb1aae…` verified, and re-swept clean.)

Other notable near-misses, each with the single change that flips it:
- **RUSH surcharge**: every fixture lands on the 500-cent floor (dearest base 1721 vs the 2500 crossover), so the "20 percent of the base" half of the `max()` is untested suite-wide — a flat-500 implementation passes. Flip: use a `DELI_SLICER_BLADE` at `RE_TIP`.
- **Subscription proration**: both fixtures produce exact integers (12000×30/30, 9000×61/30), so §2.8's "exactly one rounding to the whole product, never a per-day rounding" is unobservable. Flip: `monthly_fee_cents=12100`.
- **Late-fee grace and ceiling**: only the 2500 cap is pinned; dropping the 24-hour grace or swapping `ceil` for `floor` still yields 2500. Flip: return at 2026-05-25.
- **Boundary-inclusivity gaps**: credit limit (0 vs a balance of 19627), locker `stored_value_cents` "at most 25000" (probed at 18000/27000), bench-day "equality passes", and the `day_window_end` "at or before" edge are each tested well off the boundary, so `>` and `>=` are indistinguishable there.
- **Agreement-by-construction / vacuous assertions**: the bench-day date-vs-capacity precedence test never makes the capacity rung fire (6 min against a 480 budget); the `part_fee_cents` assessment and decline tests both assess at `CHIP_REPAIR` whose parts fee is 0, matching the item's initial value, so an implementation that never writes the field passes; the resume re-anchor is a no-op because the clock never leaves the anchor date.
- **Ledger ordering**: `["GRANTED","EXPIRED","GRANTED"]` holds only because `store.order_key` breaks equal-`created_at` ties on a private insertion counter `_seq`; a UUID tiebreak would make it a coin flip.

Two fairness risks worth flagging (both currently passing, so not deleted under the protocol): `test_voiding_an_invoice_restores_the_allowance_it_consumed` asserts `allowance_applied is False` after a void, and `test_spilled_stop_reschedules_onto_the_next_eligible_run` asserts `spilled_from_route_run_id` survives a successful reschedule — the PRD was grepped and **neither side effect is stated**; the void sentence and the reschedule enumeration are both otherwise exhaustive. One over-report from the audit was corrected: the `day_window_start == "08:00"` assertion is *not* unfair, since the PRD writes the literal `08:00`/`17:00` in its defaults sentence.

**Final per-round result — 8/8 rounds clean:** rounds 1-8 all `127/127 passed, 0 failed, 0 errors, 0 skipped` (~77-85s per round).

**Orchestrator independent verification of the clean pass:** all 8 `results.N.json` carry **127 individual rows** (not just a counter), status set exactly `{'passed'}`, sorted-test-name sha256 `cf036bd02e00` **identical across all 8 rounds**; 127 `def test_` == 127 `Design:` tags; 0 `skip`/`xfail`/`skipif`; `find … -newer results.1.json -name '*.py'` empty (no source touched after the sweep).

## Step 8: Finalize PRD — SKIPPED — 2026-08-09T14:36:00.000Z

Skip condition met exactly: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**. There is no `<step_7_diff>` to patch against, so no `PRD_FINALIZED.md` is produced and Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-09T15:15:00.000Z

Done. `PRD_COMPLETED.md` is written.

### Scale

| | PRD.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 613 | 619 (+6, from 2 new paragraphs in §2.2/§2.4) |
| chars | 126,350 | 152,136 (**+25,786**) |

39 diff hunks, all change/add — nothing deleted. **44 pins total: 33 ambiguity-pins, 11 mismatch-revisions.** Route surface cross-checked: impl's 85 `(method, path)` pairs are byte-identical to the §4 table's 85.

### Changes

**Global (§2)**
- §2.1 — revise — mismatch — ownership: listings are *not* account-scoped (only the per-invoice line listing is); an unresolvable owning account passes the rung; the allowance-entry-through-subscription path never runs (that GET excludes AccountOwner) — `routes_requests.py:162`, `routes_billing.py:251`, `services.py:26`
- §2.1 — revise — mismatch — technician run-attachment applies to exactly `arrive` and `pickup`; everything else needs only *some* Technician row — `services.py:43`, `routes_route.py:361`, `routes_requests.py:347`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 alnum — `envelope.py:12`
- §2.2 — insert — ambiguity — `api_request_timestamp` is **wall-clock**, not the logical clock — `envelope.py:16`
- §2.2 — insert — ambiguity — `message` advisory; absent/non-object body ≡ `{}`; undeclared fields ignored; unknown path/method → `ERR_VALIDATION` 404/405 — `ladder.py:88`, `app_factory.py:41`
- §2.3 — insert — ambiguity — pagination must be canonical integers (`+10`/`010`/`10.0` rejected); offset past end returns empty + `has_more` false — `ladder.py:297`
- §2.3 — insert — ambiguity — equal-`created_at` ties break on a private insertion counter, never `id`; same rule in all internal selectors; global `/invoice-lines` uses default order, not `sequence_index` — `store.py:60,75`
- §2.3 — insert — ambiguity — filter semantics: exact string compares, `run_date`/`billing_period` as strings, enum filters → `ERR_INVALID_ENUM`, `cycle_index` → `ERR_VALUE_OUT_OF_RANGE`, undeclared params ignored — `routes_route.py:123`, `ladder.py:272`
- §2.4 — insert — ambiguity — fixed projections, no private fields leak, null never omitted, **complete derived-vs-stored field list** — `serializers.py` (whole)
- §2.4 — insert — ambiguity — version granularity: no-op PATCH bumps; inspection chain bumps once; derived-only rows never bump (BenchDay, run on spill/reschedule/skip); created rows stay at 1; subscription bumped once on invoice vs once-per-item on void — `routes_accounts.py:92`, `services.py:325`, `routes_route.py:290,339`, `routes_billing.py:208,328`
- §2.5 — insert — ambiguity — `current_utc` echoed **verbatim**; every other instant rendered `.mmmZ`; input accepts offsets/fractions — `clock.py:62,123`, `routes_config.py:44`
- §2.6 r8 — revise — mismatch — AccountOwner half not applied on listings
- §2.6 r15 — insert — ambiguity — dispatch-shed stop can never be rescheduled — `routes_route.py:314,422`
- §2.6 r27 — revise — mismatch — dead on reschedule (selector pre-filters zone) — `services.py:414`
- §2.6 r33 — insert — ambiguity — window computed on reschedule; disjoint from rung 50 — `services.py:434`
- §2.6 r48 — insert — ambiguity — reachable only under PER_VISIT — `routes_billing.py:145`
- §2.6 r52/r53 — revise — mismatch — both dead on reschedule; surfaces as `ERR_NO_ELIGIBLE_RUN` — `services.py:419,425`
- §2.11 — revise — mismatch — no path in the API carries a parent+child id pair, so the rule never fires

**Workflows (§3)**
- §3.1 — revise — mismatch — plan-tier `code` uniqueness is *not* enforced — `routes_config.py:67`
- §3.1 — insert — ambiguity — PATCH: explicit null ignored, other fields immutable, empty PATCH still bumps — `routes_accounts.py:89`
- §3.2 — insert — ambiguity — `skip_count_this_cycle` reporting-only; run not bumped; skip ignores run status — `routes_subscriptions.py:275`
- §3.3 — insert — ambiguity — `locker_site_code`/`locker_high_value_authorized` stored & echoed on any channel — `routes_requests.py:121`
- §3.3 — insert — ambiguity — `charged_service_cents` written **only at invoicing**, so `final_total_cents` is parts-only until then, and void does not reset it — `serializers.py:40`, `routes_billing.py:187`
- §3.4 — revise — mismatch — stop `sequence` uniqueness is *not* enforced — `routes_route.py:193`
- §3.4 — insert — ambiguity — reported `booked_service_minutes`/`committed_minutes_provisional`/`stop_service_minutes` always use the provisional variant, even post-dispatch — `serializers.py:295,311,330`
- §3.5 — insert — ambiguity — dispatch loop halts when no `SCHEDULED` stop remains; 25-min return buffer unconditional; over-budget dispatch still succeeds — `routes_route.py:407,430`
- §3.5 — insert — ambiguity — spill leaves `route_run_id` intact; source run not bumped — `routes_route.py:290`
- §3.5 — insert — ambiguity — **`spilled_from_route_run_id` survives reschedule**; only the window check can fire — `routes_route.py:339`
- §3.5 — insert — ambiguity — dispatch-shed stop is a dead end — `routes_route.py:313`
- §3.6 — insert — ambiguity — assignment writes nothing on the request and is not idempotent (second call strands the first compartment) — `routes_requests.py:467`
- §3.6 — revise — mismatch — abandonment overwrites the work axis from **any** state, `DELIVERED → ABANDONED` being the common case — `routes_lockers.py:186`
- §3.7 — insert — ambiguity — bench intake: empty item list → `ERR_ITEM_NOT_IN_CUSTODY`; no fulfilment from-state at all — `routes_requests.py:384`
- §3.7 — insert — ambiguity — the decline `RESTORED` leg is **unreachable** (invoicing needs COMPLETED, decline needs IN_SERVICE+ASSESSED) — `routes_requests.py:592`
- §3.7 — insert — ambiguity — declined item keeps `BENCH` custody forever; release is via `bench_day_id = null` — `routes_requests.py:591`
- §3.8 — insert — ambiguity — `substituted` reporting-only; issue imposes no request precondition and permits duplicate open issues — `routes_loaners.py:96`
- §3.9 — insert — ambiguity — claim creation tests only `delivered_at`, never `service_status`; `DELIVERED` is approval's requirement — `routes_warranty.py:26,116`
- §3.9 — revise/insert — ambiguity — `abuse_finding` reporting-only; denial imposes no item-state condition — `routes_warranty.py:229`
- §3.9 — insert — ambiguity — credit basis takes the first matching line — `services.py:226`
- §3.9 — insert — ambiguity — link six leaves an `UNBILLED` original untouched and never re-runs — `routes_warranty.py:212`
- §3.10 — insert — ambiguity — step five: null assessed tier → 0 parts fee; REWORK short-circuits all three steps — `routes_billing.py:88,103`
- §3.10 — insert — ambiguity — late-fee line exposes no loaner reference; `sequence_index` rewritten on every append — `services.py:178,192`
- §3.10 — revise — mismatch — issuing does **not** freeze totals (all recomputed live, every status incl. VOID); `outstanding_balance_cents` derived, not incremented — `serializers.py:55,79`, `routes_billing.py:296`
- §3.10 — insert — ambiguity — **void resets `allowance_applied` to false**, keeps charged amounts, leaves `CREDITED` at `CREDITED` — `routes_billing.py:330`

### Hypothesis verdicts

- **(a) unnumbered preconditions — CONFIRMED, but smaller than the 57-rung scale predicted.** The impl is unusually disciplined: every route walks the rungs in numeric order with inline `# Rung N` markers. The real finds were *absences* rather than extra checks — bench intake has no fulfilment from-state, loaner issue has no request precondition, locker assignment has no idempotency guard, claim creation has no item-status test.
- **(b) projections — CONFIRMED.** Pinned the whole derived-vs-stored split plus the three hidden private fields (`_seq`, `_invoice_id`, `_loaner_issue_id`).
- **(c) ordering/tie-breaks — CONFIRMED.** `store.order_key` = `(created_at, _seq)`; every list and every internal selector uses it; `id` is never a sort key.
- **(d) version granularity — CONFIRMED,** with a genuine asymmetry found: invoicing bumps the subscription once (`routes_billing.py:209`), void bumps it once per restored item (`:329`).
- **(e) cascade legs that don't fire — CONFIRMED and extended.** Beyond the two the PRD names, link six is silently skipped for an `UNBILLED` original.
- **(f) filter semantics — CONFIRMED.** Off-enum → `ERR_INVALID_ENUM`; `run_date`/`billing_period` string compares; unknown params ignored; strict canonical-integer pagination.
- **(g) the two grepped-for side effects — BOTH CONFIRMED.** `allowance_applied = False` at `routes_billing.py:330`; `spilled_from_route_run_id` never cleared at `routes_route.py:339-343`.
- **(h) under-exercised calc branches — REFUTED as PRD gaps.** All four (rush `max` floor, single-rounding proration, 24-h grace + `ceil`, `part_fee_cents`) are already pinned uniquely by §2.8/§3.8/§3.10 and match `calcs.py` exactly. Only the `assessed_damage_tier is None → 0` case was added, which the PRD did not cover.
- **(i) boundary inclusivity — REFUTED as PRD gaps.** Every one checked (`credit_gate >`, `projected > 25000`, `booked + incoming > budget`, `end > day_window_end`, `provisional > budget`, `amount > due`, `now >= hold_expires_at`, `now >= last_released + 30m`, `<= midnight − 48h`, `<= delivered + 30d`) already matches the PRD's stated strictness. No edits.
- **(j) SoD on deny — REFUTED.** The guard *is* present (`routes_warranty.py:235`) and the PRD's "applies identically" claim is accurate; Step 7's mutation passing merely means no test exercises it. What was pinned instead is the real asymmetry: approve requires the item at `DELIVERED`, deny requires nothing.
- **(k) four reachability findings — ALL FOUR CONFIRMED by re-derivation,** plus two more of the same kind: rungs **52 and 53** are dead on reschedule too, because `select_receiving_run`'s cap and minute filters are arithmetically identical to the post-selection re-checks.
- **(l) technician scoping — CONFIRMED,** with one correction to the hypothesis: the per-invoice line listing *is* account-scoped, so "list endpoints are not account-scoped" needed a carve-out.
- **(m) timestamps — CONFIRMED.** Only `to_iso8601`/`current_utc` echoes; everything else renders `.mmmZ`. Bonus find: `api_request_timestamp` is wall-clock, not the logical clock.
- **(n) write-only fields / unenforced claims — CONFIRMED, richest cluster after (a).** Unenforced: plan-tier `code` uniqueness, stop `sequence` uniqueness, the §2.11 different-parent rule, the §2.1 allowance-entry ownership path. Write-only: `abuse_finding`, `skip_count_this_cycle`, `substituted`, `bevel_angle_degrees`, `price_tier`, `account_type`, `contact_email`, `resulting_invoice_status`.

**Orchestrator final verification:** no `*.py` under `test_suite/`, `test_helpers/` or `implementation/` is newer than `results.1.json` (Step 9 touched no code); `grep '^#'` heading lists of `PRD.md` and `PRD_COMPLETED.md` are **identical** (no new sections); table rows 161 → 161 (no endpoint/error table row added or lost); 613 → 619 lines, 18,157 → 22,196 words; `PRD_FINALIZED.md` correctly absent.
