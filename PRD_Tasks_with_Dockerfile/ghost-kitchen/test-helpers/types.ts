export interface ResponseMetaBase {

  api_request_id: string;

  api_request_timestamp: string;
}

export interface PaginationMeta {
  limit: number;
  offset: number;
  total_count: number;
  has_more: boolean;
}

export type SuccessResponseType = 'object' | 'array';
export type ErrorResponseType = 'error';

export interface ApiSuccessEnvelope<T> {
  meta: ResponseMetaBase & Partial<PaginationMeta>;
  response_type: SuccessResponseType;
  data: T;
}

export interface ErrorResponseData {

  error_id: string;

  message: string;

  details?: Array<{ field: string; issue: string }>;
}

export interface ApiErrorEnvelope {
  meta: ResponseMetaBase;
  response_type: ErrorResponseType;
  data: ErrorResponseData;
}

export type ApiResponse<T> = ApiSuccessEnvelope<T> | ApiErrorEnvelope;

export enum MealOrderStatus {
  PREPARING = 'PREPARING',
  COOKING = 'COOKING',
  QUALITY_CHECK_PENDING = 'QUALITY_CHECK_PENDING',
  COMPLETE = 'COMPLETE',
}

export enum RecipeStatus {
  PLANNING = 'PLANNING',
  READY_FOR_COOKING = 'READY_FOR_COOKING',
  CANCELLED = 'CANCELLED',
}

export enum CookingStepStatus {
  PENDING = 'PENDING',
  SCHEDULED = 'SCHEDULED',
  ASSIGNED = 'ASSIGNED',
  CANCELLED = 'CANCELLED',
}

export enum TaskExecutionStatus {
  PROPOSED = 'PROPOSED',
  ACKNOWLEDGED = 'ACKNOWLEDGED',
  BOUND = 'BOUND',
  FINALIZED = 'FINALIZED',
  REJECTED = 'REJECTED',
  CANCELLED = 'CANCELLED',
}

export enum RequiredUtensil {
  SPATULA_ATTACHMENT = 'SPATULA_ATTACHMENT',
  WHISK_HEAD = 'WHISK_HEAD',
  NONE = 'NONE',
}

export enum UserRole {
  HeadChef = 'HeadChef',
  Operator = 'Operator',
}

export interface MealOrder {
  id: string;
  order_name: string;
  status: MealOrderStatus;
  total_payment: number;
  cost_balance: number;
  food_quality_score: number;
  created_at: string;
  updated_at: string;
}

export interface Recipe {
  id: string;
  meal_order_id: string;
  name: string;
  status: RecipeStatus;
  start_time: number;
  end_time: number;
  created_at: string;
  updated_at: string;
}

export interface CookingStep {
  id: string;
  recipe_id: string;
  meal_order_id: string;
  task_type: string;
  status: CookingStepStatus;
  required_utensil: RequiredUtensil;
  start_time: number;
  end_time: number;
  duration_minutes: number;
  created_at: string;
  updated_at: string;
}

export interface UtensilCapability {
  id: string;
  name: RequiredUtensil.SPATULA_ATTACHMENT | RequiredUtensil.WHISK_HEAD;
  installed_date: string;
}

export interface CookingStation {
  id: string;
  meal_order_id: string;
  station_name: string;
  station_type: string;
  ingredient_and_energy_cost_per_minute: number;
  utensil_capabilities: UtensilCapability[];
  created_at: string;
  updated_at: string;
}

export interface TaskExecution {
  id: string;
  meal_order_id: string;
  cooking_step_id: string;
  station_id: string;
  status: TaskExecutionStatus;
  override_quality_check: boolean;
  quality_check_override_penalty_applied: boolean;
  is_rushed_order: boolean;
  provisional_cost: number;
  final_cost: number | null;
  created_at: string;
  updated_at: string;
}

export interface FoodSafetyProtocol {
  id: string;
  meal_order_id: string;
  station_id_1: string;
  station_id_2: string;
  reason?: string | null;
  created_at: string;
}

export interface CreateMealOrderPayload {
  order_name: string;
  total_payment: number;
}

export interface UpdateMealOrderPayload {
    total_payment?: number;
}

export interface CreateRecipePayload {
  name: string;
  start_time: number;
  end_time: number;
}

export interface UpdateRecipeStatusPayload {
  status: RecipeStatus.READY_FOR_COOKING | RecipeStatus.CANCELLED;
}

export interface CreateCookingStepPayload {
  task_type: string;
  required_utensil?: RequiredUtensil;
  start_time: number;
  end_time: number;
}

export interface CreateCookingStationPayload {
  station_name: string;
  station_type: string;
  ingredient_and_energy_cost_per_minute: number;
}

export interface AddUtensilCapabilityPayload {
  name: RequiredUtensil.SPATULA_ATTACHMENT | RequiredUtensil.WHISK_HEAD;
  installed_date: string;
}

export interface TaskExecutionPayload {
  cooking_step_id: string;
  station_id: string;
  override_quality_check?: boolean;
}

export interface CreateFoodSafetyProtocolPayload {
  station_id_1: string;
  station_id_2: string;
  reason?: string | null;
}
