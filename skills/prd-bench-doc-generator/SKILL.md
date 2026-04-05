---
name: prd-bench-doc-generator
description: Generate a natural-language PRD document from a scaffold YAML file. Transforms structured seed tables (entities, state machines, calculations, validations, endpoints, errors, roles) into a prose-style Product Requirements Document with deliberate information scattering. Use when the user has a scaffold YAML and wants to generate a prd.md from it.
---

# PRD Benchmark Document Generator

## Input / Output

### Input

1. **Scaffold YAML 路径**：一个由 `prd-bench-scaffold-generator` 生成的完整种子表 YAML 文件路径
2. **输出文件夹路径**：PRD 文件的输出目录

### Output

在输出文件夹下生成 `prd.md`——一份用自然语言撰写的 Product Requirements Document。

---

## 核心原则：精确合约 vs. 散布逻辑

PRD 中的信息分为两类，写作策略截然不同：

### 🔒 合约级规范（必须精确、无歧义）

这些内容决定了 API 的**结构合约**——response 长什么样、字段叫什么类型、分页怎么工作。如果这些写不清楚，任何合理的实现都可能与固定的 test 不兼容，benchmark 就失效了。

必须精确定义的内容：
- **Response envelope 格式**：完整的 JSON 示例（success + error），明确每个 meta 字段的名称、类型、语义
- **Pagination 机制**：`limit`/`offset` 参数名、默认值、最小/最大值、meta 中的 `total_count`/`has_more` 字段
- **公共资源属性**：`id`（UUID）、`created_at`（ISO 8601 UTC）、`updated_at`、`version`（integer, 每次修改递增）的精确语义
- **认证 header**：`X-User-ID` 和 `X-User-Role` 的确切名称
- **状态码规则**：创建新资源 201，修改已有资源 200
- **精度规则**：小数位数、舍入方法（如 "round half up"）
- **OCC 机制**：version 字段的行为（省略则跳过检查，不匹配则 ERR_STALE_DATA）
- **排序规则**：列表端点默认按 `created_at` 升序
- **角色枚举**：所有角色名的精确拼写
- **状态枚举值**：每个状态的精确字符串（如 `PENDING_REVIEW` 而非 `pending review`）
- **认证枚举值**：所有认证类型的精确字符串
- **Error ID 格式**：所有 error_id 的精确字符串和对应 HTTP status

### 🌫️ 业务逻辑（故意散布、增加推断难度）

这些内容是 benchmark 区分度的来源——LLM 必须从散落的叙述中自行拼装完整的实现。

应该散布的内容：
- 每个 endpoint 接受哪些字段（分散在 §3 的多个子节中）
- 计算公式的具体算法（用叙事而非伪代码）
- 数值阈值/常量（嵌入业务语句中）
- 实体间的外键关系（通过动作暗示）
- 验证规则的触发条件（error 表不含条件列）
- 状态转换的前置条件和副作用（叙述而非状态图）

---

## PRD 结构模板

```markdown
# {domain_name 转标题} API — Product Requirements Document

## 1. Introduction
## 2. Global Specifications & System-Wide Principles
  ### 2.1. User and Role-Based Access Control
  ### 2.2. API Response Structure
  ### 2.3. Pagination
  ### 2.4–2.N. [每个跨切面关注点一个子节]
## 3. Business Logic & Workflows
  ### 3.1–3.N. [每个业务流程/生命周期一个子节]
## 4. Endpoint Definitions
## 5. Error Code Catalogue
```

---

## 章节生成规则

### §1. Introduction

从 YAML `scenario` 改写为 1 段正式英文介绍。产品经理视角，说明系统目的。

### §2. Global Specifications（🔒 精确区域）

此章节中的大部分内容属于**合约级规范**，必须写得精确无歧义。

#### §2.1 User and Role-Based Access Control

- 明确写出 header 名称：`X-User-ID` 和 `X-User-Role`
- 明确列出所有角色名的精确拼写（如 `ChargeNurse`, `AttendingPhysician`）
- 提及 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 和 `ERR_INSUFFICIENT_PERMISSIONS`

#### §2.2 API Response Structure（最关键的合约子节）

**必须给出完整的 JSON 示例**，包括：

Success response：
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
  "response_type": "object",
  "data": { }
}
```

Error response：
```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

**在 JSON 示例之后**，逐字段解释语义：
- `api_request_id`：server-generated unique identifier，格式说明
- `api_request_timestamp`：ISO 8601 UTC，精确到 3 位小数
- `response_type`：`"object"` | `"array"` | `"error"` 的枚举
- `data`：业务载荷（对象、数组或空对象）
- pagination 字段（`limit`, `offset`, `total_count`, `has_more`）仅在 list 端点出现
- error 响应的 `error_id` 和 `message` 字段

#### §2.3 Pagination

- 明确 `limit` 默认值（10）、最小值（1）、最大值（100）
- 明确 `offset` 默认值（0）
- 明确排序规则（`created_at` ascending）
- 明确 meta 中的 pagination 字段名

#### §2.4 System Integrity and Consistency

描述层级一致性原则（从 `state_machines` 的 cascade/revert 提取）：
- 父状态变化 → 子资源自动跟随
- 子变化 → 父可能自动重新评估
- `updated_at` 和 `version` 随每次 mutation 递增

#### §2.5+ 领域特定跨切面原则

每个主题一个子节，从 `calculations` 和 `validations` 提取。例如：
- 财务/账本原则（ledger 规则）
- 安全/合规治理原则
- 资源利用协议（周转间隔等）
- **嵌套资源验证**：从左到右路径验证规则
- **公共资源属性**：`id`（UUID）、`created_at`/`updated_at`（ISO 8601 UTC with 3 fractional digits）、`version`（integer）的精确语义。指出哪些实体可能省略 `updated_at`（如 common_fields: false 的不可变实体）
- **精度与舍入**：从 `calculations.precision` 提取，明确写出 "2 decimal places" 和 "round half up"
- **OCC**：`version` 在 request body 中可选，不匹配则 `ERR_STALE_DATA`，省略则跳过检查

### §3. Business Logic & Workflows（🌫️ 散布区域）

这是 PRD 的**核心章节**，信息散布规则在此密集应用。

**子节划分策略**：
1. 顶层实体生命周期 → 一个子节
2. 中间层级实体的创建与管理 → 一个子节
3. 核心操作实体的提议与审批流程 → 一个子节（最长）
4. 配对/限制规则 → 一个子节
5. 安全/合规评分规则 → 一个子节
6. 成本/费用计算规则 → 一个子节
7. 结算/终结规则 → 一个子节

**子节内的写作要求**：
- 字段名用 backtick 嵌入叙事句子，不提供字段列表
- 状态转换用叙述描述前置条件和副作用，不画状态图（但状态值用精确的大写字符串，如 `PENDING_REVIEW`）
- 计算逻辑用业务叙事，不用伪代码
- 在叙述中自然提及 error_id（如"rejected with `ERR_XXX`"），但不集中解释触发条件
- 同一 endpoint 的输入参数分散到不同子节

### §4. Endpoint Definitions

表格上方写 1 段说明状态码的通用规则（如创建新资源 201，修改已有资源 200）。

从 YAML `endpoints` 生成一张总览表。核心原则：**表格保持极简，不暴露每个接口的输入输出细节**。读者必须回到 §3 的叙述中才能拼出完整的 request/response body。参考 example-prd.md 的做法。

### §5. Error Code Catalogue

从 YAML `errors` 生成一张总览表。核心原则：**表格不包含触发条件**，触发条件散布在 §2 和 §3 的叙述中。参考 example-prd.md 的做法。

---

## 信息散布规则（仅应用于 §3）

以下规则**仅应用于 §3 Business Logic**。§2 中的合约内容不受这些规则约束。

### 规则 1：字段名嵌入叙事

YAML `entities` 中的每个字段名必须在 §3 的某段落中以 backtick 出现至少一次。不提供字段列表或 schema 表。

### 规则 2：参数跨章节分散

同一 endpoint 的输入参数分布在 ≥2 个子节中。核心参数在流程子节，安全/覆盖参数在安全规则子节。

### 规则 3：算法用叙事

计算逻辑用业务叙事描述。用 "conservatively estimates"、"processes in chronological order" 等表述，不用伪代码或数学公式。

### 规则 4：常量内嵌语境

数值阈值嵌入业务语句。可利用单位转换增加推断难度（"100 hours" → 需换算为 6000 分钟）。

### 规则 5：关系通过动作表达

不声明外键。通过 "payload containing the `procedure_id`" 暗示关系。

### 规则 6：Endpoint 表极简

不暴露 request body / response body / side effects，读者必须从 §3 推断。

### 规则 7：Error 表无条件

不暴露触发条件，触发条件散布在 §2 和 §3 中。

---

## 写作风格

- **语言**：英文
- **视角**：产品经理对工程师——先领域、后实现
- **主语**：自动行为 → "the system"；用户操作 → 角色名
- **段落密度**：3-6 句/段，每句至少一个系统行为或约束
- **术语一致性**：术语引入后全文保持一致
- **冗余加固**：同一概念可在不同 section 从不同角度重复（强化而非矛盾）
- **状态值精确**：在叙述中用精确的大写字符串引用状态（`ACTIVE`, `PENDING_REVIEW`）

---

## 质量检查

### 合约精确性检查（§2）
- [ ] §2.2 包含完整的 success/error JSON 示例，字段名精确
- [ ] §2.2 逐字段解释了 meta 中每个字段的语义
- [ ] §2.3 明确写出了 limit/offset 的默认值、最小值、最大值
- [ ] §2.3 明确写出了排序规则
- [ ] 公共资源属性（id, created_at, updated_at, version）的类型和格式已精确定义
- [ ] 精度规则（小数位数 + 舍入方法）已明确写出
- [ ] OCC 机制已精确描述
- [ ] 所有角色名精确拼写
- [ ] 所有状态枚举值精确字符串
- [ ] 所有认证枚举值精确字符串

### 散布规则检查（§3）
- [ ] 每个 `entities` 字段名都在 §3 以 backtick 出现过
- [ ] 每个 `calculations` 常量都以业务语境嵌入（无裸常量定义）
- [ ] 每个 `calculations` 公式都以叙事形式表达（无伪代码）
- [ ] 每个 `errors.error_id` 都在 §2 或 §3 被提及过
- [ ] 核心操作 endpoint 的参数分布在 ≥2 个子节中
- [ ] §3 中没有任何字段列表或 schema 表

### 结构检查（§4 + §5）
- [ ] §4 endpoint 表不包含 request body / response body / side effects
- [ ] §5 error 表不包含触发条件

---

## 参考样本（必读）

以下两个文件是一组完整的 input → output 样本。生成新 PRD 时，先读取这两个文件理解转换关系：

- **输入样本**（scaffold YAML）：[example-scaffold.yaml](example-scaffold.yaml) — hospital-shifts 的完整种子表
- **输出样本**（目标 PRD）：[example-prd.md](example-prd.md) — 由上述种子表生成的 PRD 文档

重点观察：
1. `example-prd.md` 的 §2.2 如何用完整 JSON 示例精确定义 response envelope
2. `example-prd.md` 的 §3 如何将 `example-scaffold.yaml` 中的字段名散布在叙述段落中
3. endpoint 表只有 4 列，error 表只有 2 列
4. 所有计算公式用叙事而非伪代码

Scaffold YAML 的结构定义见 [prd-bench-scaffold-generator](../prd-bench-scaffold-generator/SKILL.md)
