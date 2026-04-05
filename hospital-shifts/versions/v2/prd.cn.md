# 医院排班系统：增强的排程控制与生命周期管理

## 1. 执行摘要

随着医院运营需求的成熟，我们需要一种更精细、更动态的方式来管理关键医疗资源。本次更新引入了一套精密的设备磨损与维护追踪系统，增强了我们对资源可用性和安全协议的控制，并优化了人员资质认证工作流。这些变更旨在通过在治疗计划生命周期中提供更深入的洞察和更强健的控制，提高财务准确性和患者治疗效果。

## 2. 系统级原则与增强

现有系统的基础原则——包括用户角色、财务责任和患者安全治理——完全保持不变。本次演进在这些原则之上进行以下增强。

### 2.1. 高级设备生命周期管理

为了更准确地模拟设备的运营生命周期，系统现在必须纳入定期维护保养的概念。设备磨损随每个运行分钟逐步累积，维护保养将此累积重置为零。这直接影响我们的财务和安全核算。

每个手术操作分钟的费用基于资源在该特定分钟的总使用指数，从资源最近一次维护保养开始计算。维护保养事件在使用时间线上建立重置点。某些专用设备根据制造商规格和操作容差采用不同的维护制度。超出其指定操作容差运行的资源将产生更高的每分钟费用，而常规设备遵循标准的 6,000 分钟深度清洁维护周期。生物风险标记由手术操作分钟的任何部分是否落入此高费用范围来决定。

任何分配的财务结果必须反映逐分钟的使用累积，确保维护保养后发生的操作按与其降低磨损状态相适应的费率收费，而累积使用量较大的操作则反映与高强度使用相关的升高风险和成本。

为此，`ChargeNurse` 现在可以通过提供 `resource_id` 和维护保养的 `at_minute` 来记录这些维护保养事件。维护保养事件的 `at_minute` 不得位于该资源的任何活跃资源锁定窗口内，也不得位于该资源的任何非终态分配窗口内。但是，在锁定或分配的确切结束时间（即其 `end_minute`）记录维护保养是允许的。违反这些约束将返回 `409 ERR_MAINTENANCE_EVENT_CONFLICT` 错误。

### 2.2. 临床准备与消毒

完整的设备维护保养将资源恢复到清洁、无菌的运行状态。因此，当在特定资源的分钟 M 记录了维护保养事件，且 M 落在一个操作完成之后但在**同一资源**上后续操作开始之时或之前，系统将此维护保养视为满足了这两个操作之间的操作间消毒要求。此豁免仅适用于使用被维护资源的操作，不影响其他资源的消毒要求。

### 2.3. 增强的操作约束

主管护士需要更直接地控制资源可用性，以支持校准或预防性检查等非临床活动。资源可以被临时锁定以支持此需求。

当 `ResourceHold`（资源锁定）处于活跃状态时，该资源被视为不可用于任何计划窗口与锁定窗口重叠的临床操作。此约束是双向执行的：操作不能在活跃锁定期间被提案或排期，锁定也不能在与已承诺分配重叠时被创建。但是，操作可以在锁定结束的确切分钟开始，或在锁定开始的确切分钟结束。需要注意的是，这些操作锁定本身不满足任何消毒要求，也不会改变设备的磨损累积。

锁定取消支持乐观并发控制：如果取消请求中包含 `version` 字段且与锁定的当前版本不匹配，操作将以 `409 ERR_STALE_DATA` 失败。

## 3. 工作流与安全协议的改进

核心提案和排期工作流正在更新以纳入这些新的系统能力，确保我们对患者安全和财务纪律的承诺得到维护。

### 3.1. 感染控制与隔离策略

在高风险情况下，感染控制策略必须更加严格。资源配对现在可以施加临时隔离期。当创建配对时带有 `quarantine_until_minute` 值，配对的两个资源都不得被排程参与任何在指定隔离分钟之前开始的新操作，无论其现有排程或可用性如何。此约束在提案和排期操作期间都会执行。

### 3.2. 高风险覆盖的更严格治理

虽然系统允许在紧急情况下进行协议覆盖，但这些操作现在需要更高级别的行政监督以确保问责。对于启用了此更严格策略的计划，任何绕过安全阈值锁定的提案在排期之前现在需要 `HospitalAdministrator` 的明确授权。

每次授权仅适用于单个特定的分配实例。授权记录从授权管理员的 `X-User-ID` 头中捕获 `authorized_by_user_id`。如果已授权的分配后来被取消或拒绝，其授权被视为已消耗，不能用于新的分配，即使是针对同一操作。

## 4. 财务控制与一致性

新的生命周期追踪能力完全集成到核算系统中以维护财务准确性。

成本估算在最终结算时基于该时刻的完整运营时间线重新计算。当资源的使用基线和该资源上的已承诺分配集合在排期和最终结算之间保持不变时，最终费用必须等于排期时的估算。影响计算的变更包括：为资源记录新的维护保养事件，或在该资源上排期额外的分配以改变累计使用指数。

为了维护基础工作流中系统的保守预测原则，初始成本估算反映了资源在所有未解决工作中的完整预计承诺——包括计划在稍后执行的操作——从其最近的维护保养基线开始测量。在排期时，系统通过考虑同一资源上的所有其他已承诺分配来重新计算分配的成本，排除目标分配自身的暂定分钟数以防止自我膨胀。最终成本计算必须准确反映每个资源何时进入其维护周期以及每个操作开始时的累计使用量。

## 5. API 合约新增

为支持这些新能力，引入了若干新资源和端点。所有现有端点的公共合约保持不变以确保向后兼容。

### 5.0. 时间窗口语义

系统中所有基于时间的窗口使用**半开区间** `[start_minute, end_minute)`，其中起始值包含，结束值不包含。分钟 M 处的事件或操作与窗口 `[A, B)` "重叠"的条件是 `M >= A` 且 `M < B`。如果两个操作或锁定在此定义下共享任何分钟，则视为重叠。在某些上下文中明确允许边界接触（按功能文档说明）。

### 5.1. 新资源
* `MaintenanceEvent`（维护事件）：记录一次维护保养事件。包含 `id`、`plan_id`、`resource_id`、`at_minute`、`created_at`、`version`。这是一个仅创建的资源，没有更新或删除操作；`version` 始终为 `1`。乐观并发控制不适用于此资源，因为它在创建后是不可变的。
* `ResourceHold`（资源锁定）：表示一个计划的不可用窗口。包含 `id`、`plan_id`、`resource_id`、`start_minute`、`end_minute`、`reason`、`status`（枚举：`ACTIVE`、`CANCELLED`）、`created_at`、`updated_at`、`version`。`status` 可以从 `ACTIVE` 转换为 `CANCELLED`，这会递增 `version`。取消操作支持乐观并发控制。
* `OverrideAuthorization`（覆盖授权）：记录对高风险覆盖的行政审批。包含 `id`、`plan_id`、`assignment_id`、`authorized_by_user_id`、`created_at`。`authorized_by_user_id` 从 `X-User-ID` 头中提取。此资源每个分配仅创建一次，此后不可变。

### 5.2. 新增字段
* `MedicalResource` 资源新增了一个可选的 `maintenance_threshold_override`（整数，可空）字段。当设置为非负整数时，它指定该特定资源开始产生升高的生物风险附加费的操作阈值（以分钟为单位）。当为 null 或缺失时，资源遵循标准维护周期阈值。值为 0 表示所有操作分钟立即适用生物风险附加费。
* `InfectionRiskPairing` 资源新增了一个可选的 `quarantine_until_minute`（整数）字段。
* `TreatmentPlan` 新增了一个可选的 `policies` 对象，包含：
  - `require_admin_auth_for_overrides`（布尔值，默认：false）：启用时，高风险覆盖分配在排期前需要行政授权。

### 5.3. 新端点

| 方法 | 路径 | 描述 | 授权角色 | 成功状态码 | 响应体 |
|:-----|:-----|:-----|:---------|:-----------|:-------|
| POST | `/treatment-plans/{planId}/maintenance-events` | 为资源记录一次新的维护保养事件。 | ChargeNurse | 201 Created | MaintenanceEvent 对象 |
| GET | `/treatment-plans/{planId}/maintenance-events` | 列出计划的所有维护保养事件（按 `created_at` 升序排列）。 | Any | 200 OK | MaintenanceEvent 对象数组 |
| GET | `/treatment-plans/{planId}/maintenance-events/{id}` | 获取特定维护保养事件。 | Any | 200 OK | MaintenanceEvent 对象 |
| POST | `/treatment-plans/{planId}/resource-holds` | 对资源设置临时锁定。 | ChargeNurse | 201 Created | ResourceHold 对象 |
| GET | `/treatment-plans/{planId}/resource-holds` | 列出计划的所有资源锁定（按 `created_at` 升序排列）。 | Any | 200 OK | ResourceHold 对象数组 |
| GET | `/treatment-plans/{planId}/resource-holds/{holdId}` | 获取特定资源锁定。 | Any | 200 OK | ResourceHold 对象 |
| POST | `/treatment-plans/{planId}/resource-holds/{holdId}/cancel` | 取消活跃的资源锁定。接受可选的 `version` 用于乐观并发控制。 | ChargeNurse | 200 OK | 更新后的 ResourceHold 对象 |
| POST | `/treatment-plans/{planId}/assignments/{assignmentId}/override-authorize` | 为覆盖提供行政授权（仅当计划策略启用时）。 | HospitalAdministrator | 201 Created | OverrideAuthorization 对象 |

所有列表端点包含标准分页元数据：`limit`、`offset`、`total_count`、`has_more`。列表端点验证指定的计划是否存在，如果计划未找到则返回 `404 ERR_PLAN_NOT_FOUND`。单个资源 GET 端点遵循现有系统中建立的层级验证模式：首先验证父计划是否存在（如果不存在则返回 `ERR_PLAN_NOT_FOUND`），然后验证特定资源是否存在且属于该计划（如果未找到或属于不同计划则返回资源特定的 404 错误）。

### 5.4. 错误码目录

| 错误 ID | HTTP 状态码 |
| :------ | :---------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_SELF_PAIRING` | 400 Bad Request |
| `ERR_DUPLICATE_PAIRING` | 409 Conflict |
| `ERR_PROCEDURE_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEDURE_NOT_PENDING_FOR_CANCEL` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_ROTATION_MINUTES` | 400 Bad Request |
| `ERR_ROTATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_PROCEDURE_MINUTES` | 400 Bad Request |
| `ERR_PROCEDURE_NOT_PENDING` | 409 Conflict |
| `ERR_CERTIFICATION_MISMATCH` | 400 Bad Request |
| `ERR_STERILIZATION_TIME_VIOLATION` | 409 Conflict |
| `ERR_INFECTION_RISK` | 409 Conflict |
| `ERR_SAFETY_SCORE_THRESHOLD_BREACHED` | 403 Forbidden |
| `ERR_INSUFFICIENT_BUDGET` | 402 Payment Required |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED` | 409 Conflict |
| `ERR_PROCEDURE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ILLEGAL_ROTATION_STATE_TRANSITION` | 409 Conflict |
| `ERR_PROCEDURES_NOT_ASSIGNED` | 409 Conflict |
| `ERR_PLAN_NOT_READY_FOR_FINALIZATION` | 409 Conflict |
| `ERR_FINALIZATION_EXCEEDS_BUDGET` | 402 Payment Required |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST` | 409 Conflict |
| `ERR_PLAN_NOT_IN_PLANNING` | 409 Conflict |
| `ERR_PAIRING_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_DATA` | 409 Conflict |
| `ERR_INVALID_THRESHOLD` | 400 Bad Request |
| `ERR_PAIRING_QUARANTINE_ACTIVE` | 409 Conflict |
| `ERR_RESOURCE_ON_HOLD` | 409 Conflict |
| `ERR_RESOURCE_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_HOLD_MINUTES` | 400 Bad Request |
| `ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT` | 409 Conflict |
| `ERR_MAINTENANCE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_EVENT_MINUTE` | 400 Bad Request |
| `ERR_MAINTENANCE_EVENT_CONFLICT` | 409 Conflict |
| `ERR_OVERRIDE_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_OVERRIDE_NOT_REQUIRED` | 409 Conflict |
| `ERR_OVERRIDE_ALREADY_AUTHORIZED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_PENDING_OR_APPROVED` | 409 Conflict |
