# 医院排班调度 API - 产品需求文档

## 1. 引言

本文档概述了医院排班调度 API 的产品需求。该系统旨在提供一个健壮的框架，用于在复杂且相互关联的临床和财务约束背景下，管理关键医疗资源的分配。该 API 管控患者治疗排程的整个生命周期，从初始规划和预算编制到费用和手术的最终确认，确保所有操作遵循严格的安全、资质认证和财务制度。

## 2. 全局规范与系统级原则

本节定义适用于整个 API 的系统级规则、原则和通用规范。

### 2.1. 用户与基于角色的访问控制

与 API 的所有交互都必须通过一组强制性 HTTP 请求头进行身份验证。每个请求必须包含 `X-User-ID` 以标识操作用户，以及 `X-User-Role` 以指定其操作身份。系统识别三种不同的角色：`ChargeNurse`（责任护士）、`AttendingPhysician`（主治医师）和 `HospitalAdministrator`（医院管理员）。未能提供有效请求头将导致 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 错误。此外，对特定操作的访问权限受角色限制。试图执行超出用户指定角色范围的操作将被拒绝，并返回 `ERR_INSUFFICIENT_PERMISSIONS` 错误。

### 2.2. API 响应结构

#### 标准成功响应格式

所有成功的 API 响应（状态码为 2xx）在其 JSON 响应体中遵循以下标准信封格式：

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- `api_request_id` 是服务器生成的请求唯一标识符，以 `req_` 开头。
- `api_request_timestamp` 是服务器生成的 ISO 8601 UTC 时间戳，包含三位小数。
- `response_type` 为 "object"（单个资源）或 "array"（资源列表）。
- `data` 字段包含资源对象或资源对象数组。对于没有数据的 2xx 响应，它包含一个空对象。除非另有说明，创建或修改资源的操作将在 data 字段中返回已创建或已更新的资源对象。
- `meta` 中的分页相关字段（`limit`、`offset`、`total_count`、`has_more`）包含在列表端点中。

#### 标准错误响应格式

所有错误的 API 响应（4xx 状态码）遵循以下标准信封格式：

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "关于错误的人类可读解释。"
  }
}
```

- 错误响应的 `meta` 对象仅包含 `api_request_id` 和 `api_request_timestamp`。
- `error_id` 是唯一的、机器可读的字符串，用于标识具体错误。
- `message` 提供关于出错原因的人类可读解释。

---

### 2.3. 分页

对于返回资源列表的端点，分页通过查询参数控制。`limit` 参数指定要返回的最大项目数。如未提供，默认为 10，最小值为 1，最大值为 100。`offset` 参数指定要跳过的项目数，默认为 0。

除非另有说明，所有列表端点按创建时间戳升序返回资源。

分页和非分页的列表响应在响应信封的 `meta` 对象中包含以下字段：`limit`、`offset`、`total_count` 和 `has_more`。

### 2.4. 系统完整性与一致性

系统在所有层级关系中维护严格的完整性约束。当父资源发生状态转换使其变为非运行状态时，系统确保所有依赖的子资源及其相关的财务承诺被适当地处理，以维护整体一致性。反之，对子资源的修改如果影响了父资源当前状态的条件，必须导致父资源的相应调整以维持层级对齐。这一原则适用于从治疗计划到各个分配的整个资源层级。对于涉及嵌套资源的任何操作，系统按逻辑顺序执行验证：首先确认父计划的存在和运行状态，然后在该上下文中验证子资源，最后应用业务特定规则。这种有序方法确保无效的容器状态被尽早捕获，防止部分或误导性的处理。为了维护这些不变量，服务器可能会在满足或违反条件时自动转换父或子资源的状态，而无需客户端对该特定资源发出显式请求。每次协调操作独立地变更父资源，更新其 updated_at 并递增其 version。

### 2.5. 财务责任原则

系统强制实施严格的财务资源管理。每个治疗计划都关联一个 `CareBudgetLedger`（医疗预算账本）。该账本是所有财务交易的唯一真实数据源，并在事件发生时触发协调操作以实时更新计划的 `cost_balance`（费用余额）。它通过 `provisional_debits`（临时借记）账户跟踪已临时承诺的资金，以及通过 `finalized_debits`（最终借记）账户跟踪已不可撤销支出的资金。系统保证在计划的整个生命周期中维护该账本的完整性，确保任何会超出计划可用余额的操作都无法执行。账本更新在触发事件（如提议、批准、拒绝、取消或最终确认）时立即发生，撤销操作仅适用于符合条件的非终态状态，以避免可能导致余额偏离其真实状态的冗余调整。当分配被取消或拒绝时，任何临时承诺都会被及时释放回可用余额，并反映在计划的 cost_balance 调整中。

### 2.6. 患者安全治理

系统通过 `PatientSafetyScoreLedger`（患者安全评分账本）执行严格的患者安全协议。这个计划级别的账本维护一个 `safety_score`（安全评分），当风险因素发生变化时触发协调操作以更新计划的 `patient_safety_score`（患者安全评分）。该评分从零开始，随着风险因素的引入而增加，但系统的内部保护机制确保它永远不会通过任何账本操作降低到零以下的初始基线。它作为风险的动态实时反映，包括在非终态状态下移除风险的撤销操作，较低的评分始终更优。系统旨在基于此实时评分标记并在某些情况下阻止会不可接受地损害患者安全的操作。

### 2.7. 资源利用与消毒协议

系统对医疗资源的使用和重复使用执行严格的协议。系统强制要求不兼容立即连续使用的手术之间有 30 分钟的周转时间，以符合 CDC 中级消毒指南。系统对该协议的冲突检查是全面的，考虑资源在其已承诺的手术排程中的全部安排。

医疗设备遵循行业标准维护周期，在运行 100 小时后需要进行深度清洁。此外，系统主动监控每个医疗资源的累计运行时间，以减轻与过度使用相关的风险。这由高生物风险政策管控。

重要的排程规则：

- 资源永远不能被重复预约：同一资源的时间区间永远不能重叠。

### 2.8. 嵌套资源检索

API 对所有针对嵌套资源的请求执行严格的层级验证协议。当端点路径包含多个资源标识符时（例如 `/treatment-plans/{planId}/ward-rotations/{rotationId}`），系统按从左到右的顺序依次验证每个标识符的存在性。请求将立即被拒绝，并返回与路径中*第一个*不对应现有资源的标识符相对应的 `404 Not Found` 错误。例如，在不存在的治疗计划下请求一个轮转值班将导致 `ERR_PLAN_NOT_FOUND`，系统甚至不会尝试定位该轮转值班。这一原则扩展到创建和修改操作，其中父计划的存在和激活状态优先于子级验证，确保操作仅在有效的运行上下文中进行。

### 2.9. 通用资源属性

所有主要的顶层资源（如治疗计划、轮转值班、手术、医疗资源和分配）包含一组标准的系统管理字段：

- `**id` (string)：** 资源的唯一系统生成标识符，格式为 UUID。
- `**created_at` (string)：** ISO 8601 UTC 时间戳（例如 `2025-05-24T10:30:00.123Z`），表示资源首次创建的时间。
- `**updated_at` (string)：** ISO 8601 UTC 时间戳，表示资源最后一次被修改的时间。此字段在资源属性发生任何变更时更新。
- `**version` (integer)：** 系统管理的整数，每次修改资源时递增。此字段可用于乐观并发控制。

对 TreatmentPlan 上的派生字段（如 cost_balance 和 patient_safety_score）的更新是会更新 updated_at 并递增 version 的变更操作。嵌套子资源（如医疗资源中的资质认证）也会获得一个唯一的 `id`（UUID）。创建后不可变的资源（如 `InfectionRiskPairing`）可以省略 `updated_at` 字段。这一约定为系统中的每个关键实体提供一致的审计跟踪和唯一可寻址性。

### 2.10. 货币值与精度

系统中所有的货币值（如预算和费用）必须以特定精度处理，以确保财务准确性并防止常见的浮点数错误。

- **内部计算：** 所有涉及货币值的内部计算（例如计算临时或最终费用）必须使用十进制算术执行。
- **最终值与舍入：** 最终费用值（如 `provisional_cost` 和 `final_cost`）以及存储在资源上的预算余额必须四舍五入到恰好 2 位小数。应使用标准的"四舍五入"方法。
- **API 表示：** API 响应体中返回的所有货币值必须表示为标准数字（非字符串），最多 2 位小数。配置/费率字段（如 `operating_cost_per_minute`）保留输入精度。

### 2.11. 乐观并发控制

修改资源状态的操作（例如批准分配、更新轮转值班状态）可以利用乐观锁定来防止并发环境中的丢失更新。客户端可以在请求体中包含资源的最新 `version` 号。如果提供的 `version` 与服务器上资源的当前版本不匹配，请求将被拒绝并返回 `ERR_STALE_DATA`。这确保用户不会基于过时数据进行操作。如果省略 version 字段，服务器将在不进行 OCC 检查的情况下处理变更。系统将此保护应用于路径中通过标识符定位特定资源的任何端点，从各个分配到计划最终确认的整个工作流程中维护一致性。

## 3. 业务逻辑与工作流

### 3.1. 治疗计划生命周期

系统中的核心组织实体是**治疗计划（Treatment Plan）**。`ChargeNurse` 通过提供用于标识的 `plan_name` 和设定 `total_budget`（总预算）来发起一个计划。创建时，系统会自动实例化其关联的 `CareBudgetLedger` 和 `PatientSafetyScoreLedger`。

生命周期的终点是最终审核和完成流程。在计划可以被最终确认之前，必须将其移动到 `FINAL_REVIEW_PENDING`（待最终审核）状态，这表示所有提议的临床活动已被明确排程或放弃，使计划准备好进行所有已发生费用的全面最终核算。到 `COMPLETED`（已完成）的最终转换是一个原子事务，仅限 `HospitalAdministrator` 执行。这一关键步骤涉及所有已发生费用的最终计算。

所有后续的排程活动（如定义轮转值班和手术）都以计划处于 `ACTIVE`（激活）状态为前提。这包括创建或修改轮转值班、手术、分配和配对。

### 3.2. 构建临床工作：轮转值班与手术

在 `ACTIVE` 状态的治疗计划中，`AttendingPhysician` 可以通过创建**轮转值班（Ward Rotations）**来构建临床工作流程。轮转值班代表一个逻辑时间块，由 `name`（名称）、`start_minute`（起始分钟，作为排程中的非负整数偏移量）和 `end_minute`（结束分钟）定义。每个轮转值班通过 `plan_id` 与父计划关联。在其生命周期中，轮转值班的状态可以是 `PLANNING`（规划中），并可变更为 `READY_FOR_ASSIGNMENT`（就绪待分配）、`COMPLETED`（已完成）或 `CANCELLED`（已取消）。当轮转值班中的所有手术都已达到其最终结果时——即每个手术要么是 `COMPLETED` 要么是 `CANCELLED`——轮转值班达到 `COMPLETED` 状态，反映该临床工作块已完全解决。无效的分钟规格（如非整数值或不满足结束时间大于开始时间）将触发验证错误，如 `ERR_INVALID_ROTATION_MINUTES`。

在轮转值班中，`AttendingPhysician` 定义一个或多个**手术（Procedures）**。每个 `Procedure` 使用 `procedure_type`（手术类型）及其自身的 `start_minute` 和 `end_minute` 创建。手术包含一个只读的 `duration_minutes` 字段，由其开始和结束时间派生。为了可寻址性和规则评估，手术响应同时包含其 `rotation_id` 和父级 `plan_id`。相同 `procedure_type` 的手术被视为可立即连续执行而无需额外协议的兼容手术。每个手术的一个关键信息是 `required_certification`（所需资质认证），它指定了医疗资源必须具有的资质等级才能被分配。可选值为 `BSL-3_CERTIFIED`、`CARDIAC_CATHETERIZATION_LAB` 或 `NONE`。如在创建时省略，默认为 `NONE`。手术的非整数或无效分钟范围将导致 `ERR_INVALID_PROCEDURE_MINUTES` 等错误。尚未达到终态结果的手术——处于 PENDING、SCHEDULED 或 ASSIGNED 状态的——代表需要持续资源协调和监督的活跃临床承诺。

`Procedure` 的 `status`（状态）直接受分配过程影响。当分配被提议时，手术移至 `SCHEDULED`（已排程）状态；确认后，变为 `ASSIGNED`（已分配）状态。最终，手术可以在最终确认流程后转换为 `COMPLETED`（已完成）状态。`READY_FOR_ASSIGNMENT` 要求轮转值班中的每个手术都处于 `ASSIGNED` 状态。轮转值班的状态必须按照 §2.4 和定义的状态机反映其手术的操作现实。当手术转换到其终态时，系统评估轮转值班的完成条件是否已满足，并相应地转换其状态以保持对齐。

`Procedure` 的取消仅在其处于 `PENDING`（待处理）状态时才可执行。取消 `WardRotation` 是一个更重大的事件，仅在轮转值班处于 PLANNING 或 READY_FOR_ASSIGNMENT 状态时才被允许。当轮转值班被取消时，系统通过处理在其范围内已分配或计划的所有资源来确保一致性。取消的轮转值班是终态。系统通过解决其范围内的依赖工作来维护一致性。更新轮转值班的状态（通过 `PUT` 端点）仅在父治疗计划处于 `ACTIVE` 状态时允许；否则请求将被拒绝并返回 `ERR_PLAN_NOT_ACTIVE`。

### 3.3. 分配流程：提议与审批

核心操作工作流是将**医疗资源（Medical Resource）分配给手术（Procedure）**。`AttendingPhysician` 通过包含 `procedure_id` 和 `resource_id` 的请求体提议一个**分配（Assignment）**。此操作创建一个 `Assignment` 资源，包含 `plan_id`、`procedure_id` 和 `resource_id`，初始状态为 `PENDING_SCHEDULE`（待排程）以等待审核。此提议触发一个多方面的验证过程，但仅针对在非终态轮转值班下仍处于 `PENDING` 状态的手术。

系统首先验证提议的 `MedicalResource`——由其 `resource_name`（资源名称）、`resource_model`（资源型号）和 `operating_cost_per_minute`（每分钟运营成本）定义——是否持有必要的资质。系统检查资源的 `resource_certifications`（资源资质认证）列表——每条记录包含认证 `name`（名称）和 `applied_date`（申请日期）——确保它包含与手术的 `required_certification` 匹配的认证。认证要被视为有效，其 `applied_date` 必须在分配提议日期当天或之前。为确保资源对高级手术具有适当资质，`AttendingPhysician` 有权通过提交新的认证（包括其 `name` 和 `applied_date`）来更新资源的档案。

接下来，提议经过操作性验证。系统评估排程约束以确保维护适当的消毒协议，然后评估感染控制政策以防止交叉感染风险。

系统的验证级联将患者安全放在首位；因此，它首先评估所有排程和安全相关的约束，然后才进行财务检查。如果这些检查通过，系统为分配计算 `provisional_cost`（临时费用）。该费用与治疗计划的可用 `cost_balance` 进行验证。如果预算充足，则创建分配。

`ChargeNurse` 负责审核和批准这些提议。他们可以将分配的 `status` 转换为 `PROTOCOL_APPROVED`（协议已批准）。最终的排程操作——将 `status` 移至 `SCHEDULED` 并将相应的 `Procedure` 移至 `ASSIGNED`——只能对当前处于 `PROTOCOL_APPROVED` 状态的分配执行。排程必须反映计划在风险分类和费用敞口方面的最新状态。此阶段的重新计算仅考虑其手术排程开始时间在当前手术之前的分配的操作负载，确保时间线固化时的财务精确度。系统通过新计算的临时费用与先前临时费用之间的净差额调整 CareBudgetLedger。完全确认后，分配达到 `SCHEDULED` 状态，准备在最终确认期间完成。

分配也可以在计划最终确认之前由 `ChargeNurse` 拒绝或取消，但这些操作受分配生命周期约束。具体而言：拒绝仅在分配处于 `PENDING_SCHEDULE` 状态时允许。取消在分配处于 `PENDING_SCHEDULE`、`PROTOCOL_APPROVED` 或 `SCHEDULED` 状态时允许。拒绝立即将分配设为 `REJECTED`（已拒绝）并将关联的手术重新打开为 `PENDING`。取消遵循类似过程并将关联的手术重新打开为 `PENDING`，确保在费用锁定之前有调整排程的灵活性——前提是变更与账本中反映的计划整体预算和安全承诺一致。这些状态转换受到严格控制以维护账本准确性，撤销操作仅适用于符合条件的非终态状态，以避免可能导致余额偏离其真实状态的冗余调整。

### 3.4. 感染控制与资源配对

系统允许 `ChargeNurse` 创建**感染风险配对（Infection Risk Pairing）**以减轻交叉感染的风险。此资源在 `plan_id` 的上下文中链接两个医疗资源 `resource_id_1` 和 `resource_id_2`，并可包含配对的可选 `reason`（原因）。配对在运行中的计划上下文中创建；因此，创建配对要求父治疗计划处于 `ACTIVE` 状态（当计划不处于 `ACTIVE` 状态时的尝试将被拒绝并返回 `ERR_PLAN_NOT_ACTIVE`）。配对在计划内按无序资源对唯一：尝试创建已存在的配对——无论是以 `{A,B}` 还是 `{B,A}` 提供——必须被拒绝并返回 `409 ERR_DUPLICATE_PAIRING`。

创建配对会约束未来的提议：系统拒绝会将已配对的资源放置在同一轮转值班中的提议分配，前提是其中一个已承诺在该轮转值班的排程中（已承诺排程包括处于 PENDING_SCHEDULE、PROTOCOL_APPROVED、SCHEDULED 或 COMPLETED 状态的分配）。强制执行发生在提议时。现有分配不受影响。

### 3.5. 遵守患者安全协议

当分配提议被评估时，它受患者安全治理原则约束。系统确定该分配是否符合高生物风险事件的条件。如果符合，将对 `PatientSafetyScoreLedger` 评估 50 分。系统对资源能力进行严格验证，自动拒绝手术的 `required_certification` 不在医院认证系统识别的标准认证选项之中的任何分配。

然后系统检查此惩罚是否会导致计划的 `safety_score` 达到或超过相当于十次标准生物风险事件的阈值。如果超过阈值，分配通常会被拒绝。但是，系统提供了故意覆盖的机制。分配请求体包含一个 `override_protocol_check` 布尔值。如果操作者将其设为 `true`，他们可以在安全评分超出的情况下强制执行分配。在这种情况下，在任何其他惩罚之上，将额外向 `safety_score` 添加 100 分。`Assignment` 资源通过 `override_protocol_check` 字段永久记录是否使用了覆盖，并通过只读的 `protocol_override_penalty_applied` 标志记录相关惩罚是否已被应用。

### 3.6. 高生物风险与临时费用计算

系统的费用计算逻辑与资源利用直接相关。当 `MedicalResource` 的总累计使用时间超过标准维护周期时长时，该资源被视为处于高生物风险状态。超过此阈值后发生的任何手术时间将按资源标准运营成本的双倍计费。

当分配被提议时，系统计算其 `provisional_cost`（临时费用）。为维持前瞻性和保守的风险概况，此计算通过将提议手术的持续时间加上资源在整个计划中其他未解决分配的预计操作负载来保守估计资源的未来使用情况，包括排在更后面执行的分配。此预测用于确定新手术时间的任何部分是否会受到高风险附加费的影响。`Assignment` 资源通过 `is_high_biorisk` 布尔标志跟踪此结果。

### 3.7. 费用最终确认与计划完成

治疗计划生命周期中的最后一步是费用最终确认流程，由 `HospitalAdministrator` 触发。在此过程中，为每个 `SCHEDULED` 状态的分配计算 `final_cost`（最终费用）。此费用必须准确考虑每个资源在所有已排程手术中的累计使用量超过维护阈值的时间点，仅对超出该时间点的分钟数应用附加费。计算按照每个资源的分配按其排程执行顺序处理。

此 `final_cost` 记录在 `Assignment` 资源上。如果最终风险计算（`is_high_biorisk`）与临时计算不同，`PatientSafetyScoreLedger` 也会相应调整。整个事务被提交。如果成功，所有临时借记被清除，计划的 `status` 被移至 `COMPLETED`（状态在层级间的对齐遵循 §2.4 和状态机）。

## 4. 端点定义

创建新的独立资源（例如治疗计划）或向集合添加新的独立资源（例如向计划添加轮转值班）的操作返回 `201 Created` 状态码。修改现有资源的操作（包括向资源的内部集合添加数据，例如向医疗资源添加认证）返回 `200 OK` 状态码。


| 方法   | 路径                                                                                      | 描述            | 授权角色                  |
| ---- | --------------------------------------------------------------------------------------- | ------------- | --------------------- |
| POST | `/treatment-plans`                                                                      | 创建新的治疗计划      | ChargeNurse           |
| GET  | `/treatment-plans`                                                                      | 列出所有治疗计划      | 任意                    |
| GET  | `/treatment-plans/{planId}`                                                             | 获取特定治疗计划      | 任意                    |
| POST | `/treatment-plans/{planId}/activate`                                                    | 激活计划          | ChargeNurse           |
| POST | `/treatment-plans/{planId}/ward-rotations`                                              | 在计划中创建新的轮转值班  | AttendingPhysician    |
| GET  | `/treatment-plans/{planId}/ward-rotations`                                              | 列出计划的轮转值班     | 任意                    |
| GET  | `/treatment-plans/{planId}/ward-rotations/{rotationId}`                                 | 获取特定轮转值班      | 任意                    |
| PUT  | `/treatment-plans/{planId}/ward-rotations/{rotationId}`                                 | 更新轮转值班状态      | ChargeNurse           |
| POST | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures`                      | 为轮转值班创建新的手术   | AttendingPhysician    |
| GET  | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures`                      | 列出轮转值班的手术     | 任意                    |
| GET  | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures/{procedureId}`        | 获取特定手术        | 任意                    |
| POST | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures/{procedureId}/cancel` | 取消特定手术        | AttendingPhysician    |
| POST | `/treatment-plans/{planId}/assignments`                                                 | 为手术提议新的医疗资源分配 | AttendingPhysician    |
| GET  | `/treatment-plans/{planId}/assignments`                                                 | 列出计划的所有分配     | 任意                    |
| GET  | `/treatment-plans/{planId}/assignments/{assignmentId}`                                  | 获取特定分配        | 任意                    |
| POST | `/treatment-plans/{planId}/assignments/{assignmentId}/reject`                           | 拒绝提议的分配       | ChargeNurse           |
| POST | `/treatment-plans/{planId}/assignments/{assignmentId}/cancel`                           | 取消分配          | ChargeNurse           |
| POST | `/treatment-plans/{planId}/assignments/{assignmentId}/protocol-approve`                 | 协议批准提议的分配     | ChargeNurse           |
| POST | `/treatment-plans/{planId}/assignments/{assignmentId}/schedule`                         | 排程已协议批准的手术    | ChargeNurse           |
| POST | `/treatment-plans/{planId}/medical-resources`                                           | 为计划创建新的医疗资源档案 | AttendingPhysician    |
| GET  | `/treatment-plans/{planId}/medical-resources`                                           | 列出计划的医疗资源档案   | 任意                    |
| GET  | `/treatment-plans/{planId}/medical-resources/{resourceId}`                              | 获取特定医疗资源档案    | 任意                    |
| POST | `/treatment-plans/{planId}/medical-resources/{resourceId}/certifications`               | 向医疗资源添加资质认证   | AttendingPhysician    |
| POST | `/treatment-plans/{planId}/infection-risk-pairings`                                     | 在计划中创建感染风险配对  | ChargeNurse           |
| GET  | `/treatment-plans/{planId}/infection-risk-pairings`                                     | 列出计划的感染风险配对   | 任意                    |
| GET  | `/treatment-plans/{planId}/infection-risk-pairings/{pairingId}`                         | 获取特定感染风险配对    | 任意                    |
| POST | `/treatment-plans/{planId}/initiate-final-review`                                       | 将计划移至待最终审核状态  | ChargeNurse           |
| POST | `/treatment-plans/{planId}/finalize-plan`                                               | 最终确认费用并完成计划   | HospitalAdministrator |


## 5. 错误码目录


| 错误 ID                                        | HTTP 状态码             |
| -------------------------------------------- | -------------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request      |
| `ERR_INSUFFICIENT_PERMISSIONS`               | 403 Forbidden        |
| `ERR_PLAN_NOT_FOUND`                         | 404 Not Found        |
| `ERR_RESOURCE_NOT_FOUND`                     | 404 Not Found        |
| `ERR_SELF_PAIRING`                           | 400 Bad Request      |
| `ERR_DUPLICATE_PAIRING`                      | 409 Conflict         |
| `ERR_PROCEDURE_NOT_FOUND`                    | 404 Not Found        |
| `ERR_PROCEDURE_NOT_PENDING_FOR_CANCEL`       | 409 Conflict         |
| `ERR_PLAN_NOT_ACTIVE`                        | 409 Conflict         |
| `ERR_INVALID_ROTATION_MINUTES`               | 400 Bad Request      |
| `ERR_ROTATION_NOT_FOUND`                     | 404 Not Found        |
| `ERR_INVALID_PROCEDURE_MINUTES`              | 400 Bad Request      |
| `ERR_PROCEDURE_NOT_PENDING`                  | 409 Conflict         |
| `ERR_CERTIFICATION_MISMATCH`                 | 400 Bad Request      |
| `ERR_STERILIZATION_TIME_VIOLATION`           | 409 Conflict         |
| `ERR_INFECTION_RISK`                         | 409 Conflict         |
| `ERR_SAFETY_SCORE_THRESHOLD_BREACHED`        | 403 Forbidden        |
| `ERR_INSUFFICIENT_BUDGET`                    | 402 Payment Required |
| `ERR_INVALID_REQUEST`                        | 400 Bad Request      |
| `ERR_ASSIGNMENT_NOT_FOUND`                   | 404 Not Found        |
| `ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE`        | 409 Conflict         |
| `ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED`       | 409 Conflict         |
| `ERR_PROCEDURE_NOT_SCHEDULED`                | 409 Conflict         |
| `ERR_ILLEGAL_ROTATION_STATE_TRANSITION`      | 409 Conflict         |
| `ERR_PROCEDURES_NOT_ASSIGNED`                | 409 Conflict         |
| `ERR_PLAN_NOT_READY_FOR_FINALIZATION`        | 409 Conflict         |
| `ERR_FINALIZATION_EXCEEDS_BUDGET`            | 402 Payment Required |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE`             | 409 Conflict         |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST`           | 409 Conflict         |
| `ERR_PLAN_NOT_IN_PLANNING`                   | 409 Conflict         |
| `ERR_PAIRING_NOT_FOUND`                      | 404 Not Found        |
| `ERR_STALE_DATA`                             | 409 Conflict         |


